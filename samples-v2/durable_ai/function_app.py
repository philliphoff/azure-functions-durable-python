import asyncio
import os
import azure.functions as func
import durable_ai
from agents import OpenAIChatCompletionsModel, set_default_openai_client
from openai import AsyncAzureOpenAI

import deterministic
import hello_world
import llm_as_a_judge
import tools

openai_client = AsyncAzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT")
    )

# Set the default OpenAI client for the Agents SDK
set_default_openai_client(openai_client)

model=OpenAIChatCompletionsModel(model="gpt-4.1", openai_client=openai_client)

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
ai_app = durable_ai.DurableAIFunctionApp(app)

ai_app.enable_agent_http_trigger()

#
# Run a simple "Hello, World!" agent.
#
@ai_app.agent(name="hello_world")
async def run_hello_world(input: str) -> str:
    return await hello_world.run(input, model)

#
# Run a deterministic agent that publishes a story.
#
# This sample demonstrates how to use a durable context to call a standard Durable Functions activity.
#
@ai_app.agent(name="deterministic")
async def run_deterministic(context: durable_ai.DurableAIOrchestrationContext) -> str:
    story = await deterministic.run(context.get_input(), model)
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
@ai_app.agent(name="tools")
async def run_tools(input: str) -> str:
    return await tools.run(input, model)
