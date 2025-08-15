import copy
import functools
import inspect
import json
import asyncio
from typing import Any, Awaitable, Dict, Iterator, Optional, Sequence, Union, overload
from agents import ModelSettings
from azure.durable_functions.models.Task import TaskBase
import azure.functions as func
from azure.durable_functions.models.DurableOrchestrationContext import DurableOrchestrationContext, RetryOptions
from pydantic_ai import Agent, Tool
from pydantic_ai.agent.abstract import AbstractAgent

class YieldTaskError(BaseException):
    def __init__(self, task: TaskBase):
        super().__init__("Halt the orchestration to return an orchestration task.")
        self.task = task

class DurableAIAgentOptions:
    def __init__(self, retry_options: Optional[RetryOptions] = None):
        self._retry_options = retry_options

    @property
    def retry_options(self) -> Optional[RetryOptions]:
        return self._retry_options

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

class DurableAIActivityOutputSchemaInput:
    output_type: str | None
    is_wrapped: bool
    output_schema: dict[str, Any] | None
    strict_json_schema: bool

class DurableAIActivityInput:
    input: str | list[Dict[str, Any]]
    instance_id: str | None
    model_name: str
    system_instructions: str | None

class DurableAgent(AbstractAgent):
    def __init__(self, app, agent: AbstractAgent):
        self.app = app
        self.agent = agent

    @property
    def model(self):
        return self.agent.model

    @property
    def name(self):
        return self.agent.name

    @name.setter
    def name(self, value):
        raise NotImplementedError("Setting name is not supported for DurableAgent.")

    @property
    def deps_type(self):
        return self.agent.deps_type

    @property
    def output_type(self):
        return self.agent.output_type

    @property
    def event_stream_handler(self):
        return self.agent.event_stream_handler

    @property
    def toolsets(self):
        return self.agent.toolsets

    @overload
    def iter(self, user_prompt=None, *, output_type=None, message_history=None, model=None, deps=None, model_settings=None, usage_limits=None, usage=None, infer_name=True, toolsets=None):
        return self.agent.iter(user_prompt, output_type=output_type, message_history=message_history, model=model, deps=deps, model_settings=model_settings, usage_limits=usage_limits, usage=usage, infer_name=infer_name, toolsets=toolsets)

    @overload
    def iter(self, user_prompt=None, *, output_type, message_history=None, model=None, deps=None, model_settings=None, usage_limits=None, usage=None, infer_name=True, toolsets=None):
        return self.agent.iter(user_prompt, output_type=output_type, message_history=message_history, model=model, deps=deps, model_settings=model_settings, usage_limits=usage_limits, usage=usage, infer_name=infer_name, toolsets=toolsets)

    async def __aenter__(self):
        # Delegate context management to the underlying agent if supported
        if hasattr(self.agent, "__aenter__"):
            return await self.agent.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Delegate context management to the underlying agent if supported
        if hasattr(self.agent, "__aexit__"):
            return await self.agent.__aexit__(exc_type, exc_val, exc_tb)
        return False

    def run(self, *args, **kwargs):
        # Provide a synchronous run method that delegates to the underlying agent
        if hasattr(self.agent, "run"):
            return self.agent.run(*args, **kwargs)
        raise NotImplementedError("Underlying agent does not implement 'run'.")

    def override(
        self,
        *,
        deps,
        model,
        toolsets,
        tools,
    ) -> Iterator[None]:
        raise NotImplementedError("DurableAgent does not support overriding.")

class DurableAIFunctionApp:
    activity_name = "pydantic-agent-activity"

    def __init__(self, app):
        self.app = app

        @app.activity_trigger(input_name="input", activity=self.activity_name)
        async def pydantic_agent_activity_trigger(input) -> str:
            activity_input = DurableAIActivityInput(**input)

            model = self.model_provider.get_model(activity_input.model_name)

            output_schema = None

            # TODO: Call real agent.

            return "test"

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
