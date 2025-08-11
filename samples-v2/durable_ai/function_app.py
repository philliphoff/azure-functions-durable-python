import os
import azure.functions as func
import durable_ai
from agents import OpenAIChatCompletionsModel, set_default_openai_client
from openai import AsyncAzureOpenAI

# Import the agent runners
import deterministic
import hello_world
import llm_as_a_judge

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

@ai_app.agent(name="hello_world")
async def run_hello_world(input):
    return await hello_world.run(input, model)

@ai_app.agent(name="deterministic")
async def run_deterministic(input):
    return await deterministic.run(input, model)

@ai_app.agent(name="llm_as_a_judge")
async def run_llm_as_a_judge(input):
    return await llm_as_a_judge.run(input, model)
