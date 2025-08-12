import copy
import functools
import inspect
import json
import asyncio
from typing import Any, Awaitable, Dict, Optional, Union
from openai import BaseModel
from openai.types.responses.response_prompt_param import ResponsePromptParam
from agents import AgentOutputSchema, AgentOutputSchemaBase, FunctionTool, Handoff, ModelResponse, ModelSettings, ModelTracing, TResponseInputItem, Tool
from azure.durable_functions.models.Task import TaskBase
import azure.functions as func
from agents.run import AgentRunner, set_default_agent_runner, Model, RunConfig
from azure.durable_functions.models.DurableOrchestrationContext import DurableOrchestrationContext, RetryOptions
from agents.tool_context import ToolContext
from agents.tool import function_schema

class YieldTaskError(BaseException):
    def __init__(self, task: TaskBase):
        super().__init__("Halt the orchestration to return an orchestration task.")
        self.task = task

class DurableAIAgentOptions(BaseModel):
    def __init__(self, retry_options: Optional[RetryOptions] = None):
        self._retry_options = retry_options

    @property
    def retry_options(self) -> Optional[RetryOptions]:
        return self._retry_options

class DurableAIModelContext:
    def __init__(self):
        self.models = {}

class DurableAIOrchestrationContext:
    def __init__(self, context: DurableOrchestrationContext, options: Optional[DurableAIAgentOptions] = None):
        self.context = context
        self.options = options
        self.tasks = {}

    async def call_activity(self, activity_name: str, input: Optional[Any] = None):
        input_json = f"{activity_name}|{json.dumps(input) if input is not None else ''}"

        if input_json in self.tasks:
            task = self.tasks[input_json]
        else:
            task = self.context.call_activity(activity_name, input)
            self.tasks[input_json] = task

        if task.is_completed:
            return task.result

        raise YieldTaskError(task)

    async def call_activity_with_retry(
            self,
            activity_name: str,
            retry_options: RetryOptions,
            input: Optional[Any] = None):
        input_json = f"{activity_name}|{json.dumps(input) if input is not None else ''}"

        if input_json in self.tasks:
            task = self.tasks[input_json]
        else:
            task = self.context.call_activity_with_retry(activity_name, retry_options, input)
            self.tasks[input_json] = task

        if task.is_completed:
            return task.result

        raise YieldTaskError(task)
    
    def get_input(self) -> Any | None:
        return self.context.get_input()

    def set_custom_status(self, status: Any):
        self.context.set_custom_status(status)

    def to_tool(self, tool: Any) -> FunctionTool:
        activity_name = tool._function._name

        async def _invoke_tool(context: ToolContext[Any], args: str) -> Any:
            if self.options is not None and self.options.retry_options is not None:
                result = await self.call_activity_with_retry(
                    activity_name=activity_name,
                    retry_options=self.options.retry_options,
                    input=args
                )
            else:
                result = await self.call_activity(activity_name, args)

            return result

        schema = function_schema(
            func=_invoke_tool,
            name_override=activity_name,
            docstring_style=None,
            description_override=None,
            use_docstring_info=False,
            strict_json_schema=False,
        )

        return FunctionTool(
            name=activity_name,
            description="",
            params_json_schema=schema.params_json_schema,
            on_invoke_tool=_invoke_tool,
            strict_json_schema=False
        )

    async def wait_for_external_event(self, event_name: str) -> Any:
        input_json = f"{event_name}"

        if input_json in self.tasks:
            task = self.tasks[input_json]
        else:
            task = self.context.wait_for_external_event(event_name)
            self.tasks[input_json] = task

        if task.is_completed:
            return task.result

        raise YieldTaskError(task)

class DurableAIActivityOutputSchemaInput(BaseModel):
    output_type: str | None
    is_wrapped: bool
    output_schema: dict[str, Any] | None
    strict_json_schema: bool

class DurableAIActivityOutputSchema(AgentOutputSchemaBase):
    def __init__(self, input: DurableAIActivityOutputSchemaInput):
        self.input = input

    def is_plain_text(self) -> bool:
        return self.input.output_type is None or self.input.output_type == "str"

    def name(self) -> str:
        return self.input.output_type if self.input.output_type is not None else "plain_text"

    def json_schema(self) -> dict[str, Any]:
        return self.input.output_schema

    def is_strict_json_schema(self) -> bool:
        return self.input.strict_json_schema

    def validate_json(self, json_str: str) -> Any:
        raise NotImplementedError("DurableAIActivityOutputSchema does not support validate_json")

class DurableAIFunctionToolInput(BaseModel):
    description: str
    name: str
    params_json_schema: dict[str, Any]
    strict_json_schema: bool

DurableAIToolInput = Union[
    DurableAIFunctionToolInput
]

class DurableAIActivityInput(BaseModel):
    input: str | list[Dict[str, Any]]
    instance_id: str | None
    output_schema: DurableAIActivityOutputSchemaInput | None
    system_instructions: str | None
    tools: list[DurableAIToolInput]

class DurableAIModel(Model):
    def __init__(self, app: func.FunctionApp, context: DurableAIOrchestrationContext, model: Model, activity_name: str, options: DurableAIAgentOptions | None = None):
        self.model = model
        self.context = context
        self.activity_name = activity_name
        self.options = options

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

        def get_tool_input(tool: Tool) -> DurableAIToolInput:
            if isinstance(tool, FunctionTool):
                return DurableAIFunctionToolInput(
                    description=tool.description,
                    name=tool.name,
                    params_json_schema=tool.params_json_schema,
                    strict_json_schema=tool.strict_json_schema
                )
            else:
                raise TypeError(f"Unsupported tool type: {type(tool)}")

        input_output_schema = None

        if output_schema is not None:
            if not isinstance(output_schema, AgentOutputSchema):
                raise TypeError("output_schema must be an instance of AgentOutputSchema")
            input_output_schema = DurableAIActivityOutputSchemaInput(
                output_type=output_schema.name(),
                is_wrapped=output_schema._is_wrapped,
                output_schema=output_schema.json_schema(),
                strict_json_schema=output_schema.is_strict_json_schema()
            )

        activity_input = DurableAIActivityInput(
            input=input,
            instance_id=self.context.context.instance_id,
            output_schema=input_output_schema,
            system_instructions=system_instructions,
            tools=[get_tool_input(tool) for tool in tools]
        )

        if (self.options is not None and self.options.retry_options is not None):
            response = await self.context.call_activity_with_retry(
                activity_name=self.activity_name,
                retry_options=self.options.retry_options,
                input=activity_input.to_dict()
            )
        else:
            response = await self.context.call_activity(
                activity_name=self.activity_name,
                input=activity_input.to_dict()
            )

        # NOTE: The response is a ModelResponse encoded as a JSON object encoded as a JSON string.

        json_response = json.loads(response)
        model_response = ModelResponse(**json_response)
        return model_response

    async def get_model_response(
            self,
            system_instructions: str | None,
            input: str | list[TResponseInputItem],
            output_schema: AgentOutputSchemaBase,
            tools: list[Tool]):
        response = await self.model.get_response(
            system_instructions=system_instructions,
            input=input,
            model_settings=ModelSettings(),
            tools=tools,
            output_schema=output_schema,
            handoffs=[],
            tracing=ModelTracing.ENABLED,
            previous_response_id=None)
        return response

    def stream_response(self, system_instructions, input, model_settings, tools, output_schema, handoffs, tracing, *, previous_response_id, prompt):
        return NotImplementedError("Not yet implemented.")

class DurableAIAgentRunner(AgentRunner):
    def __init__(self, app, context: DurableAIOrchestrationContext, model_context: DurableAIModelContext, activity_name: str, options: DurableAIAgentOptions | None = None):
        self.app = app
        self.context = context
        self.model_context = model_context
        self.activity_name = activity_name
        self.options = options

    async def run(
        self,
        starting_agent,
        input,
        **kwargs):
        run_config = kwargs.get("run_config")

        if (run_config is None):
            run_config = RunConfig()

        model = run_config.model or starting_agent.model

        updated_model = DurableAIModel(self.app, self.context, model, self.activity_name, self.options)

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
        async def agent_activity_trigger(input) -> str:
            activity_input = DurableAIActivityInput(**input)
            model = self.model_context.models[activity_input.instance_id]

            output_schema = None

            if (activity_input.output_schema is not None):
                output_schema = DurableAIActivityOutputSchema(activity_input.output_schema)

            async def invoke_tool(tool_context: ToolContext, params: str) -> Awaitable[Any]:
                return await "Test"

            def to_tools(tool: DurableAIToolInput) -> Tool:
                if isinstance(tool, DurableAIFunctionToolInput):
                    return FunctionTool(
                        description=tool.description,
                        name=tool.name,
                        on_invoke_tool=invoke_tool,
                        params_json_schema=tool.params_json_schema,
                        strict_json_schema=tool.strict_json_schema
                    )
                else:
                    raise TypeError(f"Unsupported tool type: {type(tool)}")

            response = await model.get_model_response(
                system_instructions=activity_input.system_instructions,
                input=activity_input.input,
                output_schema=output_schema,
                tools=[to_tools(tool) for tool in activity_input.tools]
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

    def agent(self, name: str, input_name: str = "input", context_name: str = "context", options: DurableAIAgentOptions | None = None):
        def agent_orchestration_trigger_wrapper(trigger):
            @self.app.orchestration_trigger(orchestration=f"{name}-orchestration", context_name="context")
            @functools.wraps(trigger)
            def agent_orchestration_trigger(context):
                input = context.get_input()

                durableAIContext = DurableAIOrchestrationContext(context)

                kwargs = {}

                sig = inspect.signature(trigger)

                for param in sig.parameters.values():
                    if param.name == context_name:
                        kwargs[param.name] = durableAIContext
                    elif param.name == input_name:
                        kwargs[param.name] = input
                    else:
                        raise ValueError(f"Unexpected parameter: {param.name}")

                async def run_agent():
                    try:
                        set_default_agent_runner(DurableAIAgentRunner(self, durableAIContext, self.model_context, self.activity_name, options))

                        return await trigger(**kwargs)
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
