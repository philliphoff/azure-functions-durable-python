import os
import azure.functions as func

from agents import Agent, Runner, OpenAIChatCompletionsModel, set_default_openai_client
from openai import AsyncAzureOpenAI

import durable_ai

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
ai_app = durable_ai.DurableAIFunctionApp(app)

ai_app.enable_agent_http_trigger()

@ai_app.agent(name="myagent")
async def run_myagent(input):
    openai_client = AsyncAzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT")
    )

    # Set the default OpenAI client for the Agents SDK
    set_default_openai_client(openai_client)

    agent = Agent(
        name="Assistant",
        instructions="You are a helpful assistant",
        model=OpenAIChatCompletionsModel(model="gpt-4.1", openai_client=openai_client))

    result = await Runner.run(
        agent,
        input=input)
    
    return result.final_output
