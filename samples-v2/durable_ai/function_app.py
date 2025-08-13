import asyncio
import json
import os
import azure.functions as func
from azure.durable_functions.models.DurableOrchestrationContext import RetryOptions
import durable_ai
from agents import set_default_openai_client
from openai import AsyncAzureOpenAI, BaseModel

import sample_agents.deterministic as deterministic
import sample_agents.hello_world as hello_world
import sample_agents.llm_as_a_judge as llm_as_a_judge
import sample_agents.tools as tools

openai_client = AsyncAzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
        # Set max retries to zero to not conflict with activity-level retry options.
        max_retries=0
    )

# Set the default OpenAI client for the Agents SDK
set_default_openai_client(openai_client)

model="gpt-4.1"

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
ai_app = durable_ai.DurableAIFunctionApp(app)

ai_app.enable_agent_http_trigger()

#
# Run a simple "Hello, World!" agent.
#
@ai_app.agent(name="hello_world")
async def run_hello_world(input: str) -> str:
    return await hello_world.run(input, model)

options = durable_ai.DurableAIAgentOptions(
    retry_options=RetryOptions(
        first_retry_interval_in_milliseconds=1000,
        max_number_of_attempts=3,
    )
)

#
# Run a deterministic agent that publishes a story.
#
# This sample demonstrates how to use a durable context to call a standard Durable Functions activity.
#
@ai_app.agent(name="deterministic", options=options)
async def run_deterministic(context: durable_ai.DurableAIOrchestrationContext) -> str:
    story = await deterministic.run(context.get_input(), model)

    context.set_custom_status("Publishing story...")

    return await context.call_activity("publish_story", story)

@app.activity_trigger(input_name="input")
async def publish_story(input: str) -> str:
    print(f"Publishing story: {input}")
    await asyncio.sleep(1)
    print(f"Story published")
    return input

#
# Run an agent that uses a language model as a judge.
#
@ai_app.agent(name="llm_as_a_judge")
async def run_llm_as_a_judge(input: str) -> str:
    return await llm_as_a_judge.run(input, model)

#
# Run an agent that uses various tools.
#
class Weather(BaseModel):
    city: str
    temperature_range: str
    conditions: str

    @staticmethod
    def from_json(data: str) -> "Weather":
        return Weather(**json.loads(data))

@app.activity_trigger(input_name="city")
def get_weather(city: str) -> Weather:
    print("[debug] get_weather called")
    return Weather(city=city, temperature_range="14-20C", conditions="Sunny with wind.")

@ai_app.agent(name="tools")
async def run_tools(context: durable_ai.DurableAIOrchestrationContext) -> str:
    return await tools.run(context.get_input(), model, [context.to_tool(get_weather)])
