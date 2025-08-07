import copy
import json
import asyncio
from typing import Any
from openai.types.responses.response_prompt_param import ResponsePromptParam
from agents import AgentOutputSchemaBase, Handoff, ModelResponse, ModelSettings, ModelTracing, TResponseInputItem, Tool
from azure.durable_functions.models.Task import TaskBase
import azure.functions as func
from agents.run import AgentRunner, set_default_agent_runner, Model, RunConfig
from azure.durable_functions.models.DurableOrchestrationContext import DurableOrchestrationContext

class YieldTaskError(Exception):
    def __init__(self, task: TaskBase):
        super().__init__("Stop running the orchestration.")
        self.task = task

class DurableAIModelContext:
    def __init__(self):
        self.models = {}

class DurableAIOrchestrationContext:
    def __init__(self, context: DurableOrchestrationContext, activity_name: str):
        self.context = context
        self.activity_name = activity_name
        self.tasks = {}

    async def call_activity(self, input: Any | None = None):
        input_json = json.dumps(input) if input is not None else ""

        if input_json in self.tasks:
            task = self.tasks[input_json]
        else:
            task = self.context.call_activity(self.activity_name, input)
            self.tasks[input_json] = task

        if task.is_completed:
            return task.result

        raise YieldTaskError(task)

class DurableAIModel(Model):
    def __init__(self, app: func.FunctionApp, context: DurableAIOrchestrationContext, model: Model):
        self.model = model
        self.context = context

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[TResponseInputItem],
        model_settings: ModelSettings,
        tools: list[Tool],
        output_schema: AgentOutputSchemaBase | None,
        handoffs: list[Handoff],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        prompt: ResponsePromptParam | None):
        # TODO: Need to uniquely identify a model invocation

        activity_input_dict = {
            "input": input,
            "instance_id": self.context.context.instance_id,
            "system_instructions": system_instructions
        }

        response = await self.context.call_activity(input=activity_input_dict)

        # NOTE: The response is a ModelResponse encoded as a JSON object encoded as a JSON string.

        json_response = json.loads(response)
        model_response = ModelResponse(**json_response)
        return model_response

    async def get_model_response(
            self,
            system_instructions: str | None,
            input: str | list[TResponseInputItem]):
        response = await self.model.get_response(
            system_instructions=system_instructions,
            input=input,
            model_settings=ModelSettings(),
            tools=[],
            output_schema=None,
            handoffs=[],
            tracing=ModelTracing.ENABLED,
            previous_response_id=None)
        return response

    def stream_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, *, previous_response_id, prompt):
        return NotImplementedError("Not yet implemented.")

class DurableAIAgentRunner(AgentRunner):
    def __init__(self, app, context: DurableAIOrchestrationContext, model_context: DurableAIModelContext):
        self.app = app
        self.context = context
        self.model_context = model_context

    async def run(
        self,
        starting_agent,
        input,
        **kwargs):
        run_config = kwargs.get("run_config")

        if (run_config is None):
            run_config = RunConfig()

        model = run_config.model or starting_agent.model

        updated_model = DurableAIModel(self.app, self.context, model)

        self.model_context.models[self.context.context.instance_id] = updated_model

        run_config = copy.copy(run_config)

        run_config.model = updated_model

        kwargs.update(run_config=run_config)

        result = await super().run(
            starting_agent=starting_agent,
            input=input,
            **kwargs)

        return result

    def run_sync(self, starting_agent, input, **kwargs):
        return NotImplementedError("Not yet implemented.")

    def run_streamed(self, starting_agent, input, **kwargs):
        return NotImplementedError("Not yet implemented.")

class DurableAIFunctionApp:
    activity_name = "agent-activity"

    def __init__(self, app):
        self.app = app
        self.model_context = DurableAIModelContext()
        @app.activity_trigger(input_name="input", activity=self.activity_name)
        async def agent_activity_trigger(input):
            model = self.model_context.models[input["instance_id"]]

            response = await model.get_model_response(
                system_instructions=input["system_instructions"],
                input=input["input"]
            )

            # Returns JSON encoded as bytes
            json_obj = ModelResponse.__pydantic_serializer__.to_json(response)

            # Return string (which will then be encoded as JSON string, sigh)
            return json_obj.decode()

    def enable_agent_http_trigger(self):
        @self.app.route(route="agents/{name}")
        @self.app.durable_client_input(client_name="client")
        async def agent_http_trigger(req: func.HttpRequest, client):
            param_name = "name"
            orchestration_name_suffix = "-orchestration"
            function_name = req.route_params.get(param_name)
            input = req.params.get("input")
            instance_id = await client.start_new(f"{function_name}{orchestration_name_suffix}", client_input=input)
            response = client.create_check_status_response(req, instance_id)
            return response

    def agent(self, name: str, input_name: str = "input"):
        def agent_orchestration_trigger_wrapper(trigger):
            @self.app.orchestration_trigger(orchestration=f"{name}-orchestration", context_name="context")
            def agent_orchestration_trigger(context):
                input = context.get_input()

                durableAIContext = DurableAIOrchestrationContext(context, self.activity_name)

                async def run_agent():
                    try:
                        set_default_agent_runner(DurableAIAgentRunner(self, durableAIContext, self.model_context))

                        return await trigger(**{input_name: input})
                    except YieldTaskError as e:
                        return e.task

                task = None

                while True:
                    task = asyncio.run(run_agent())

                    if not isinstance(task, TaskBase):
                        break

                    yield task

                return task
            return agent_orchestration_trigger
        return agent_orchestration_trigger_wrapper
