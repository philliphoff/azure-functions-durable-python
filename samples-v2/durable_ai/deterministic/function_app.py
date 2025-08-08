from dataclasses import dataclass
import os
import azure.functions as func

from agents import Agent, Runner, OpenAIChatCompletionsModel, UserError, set_default_openai_client
from openai import AsyncAzureOpenAI, BaseModel

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

    model=OpenAIChatCompletionsModel(model="gpt-4.1", openai_client=openai_client)

    # Set the default OpenAI client for the Agents SDK
    set_default_openai_client(openai_client)

    """
    This example demonstrates a deterministic flow, where each step is performed by an agent.
    1. The first agent generates a story outline
    2. We feed the outline into the second agent
    3. The second agent checks if the outline is good quality and if it is a scifi story
    4. If the outline is not good quality or not a scifi story, we stop here
    5. If the outline is good quality and a scifi story, we feed the outline into the third agent
    6. The third agent writes the story
    """

    story_outline_agent = Agent(
        name="story_outline_agent",
        instructions="Generate a very short story outline based on the user's input.",
        model=model
    )

    @dataclass
    class OutlineCheckerOutput:
        good_quality: bool
        is_scifi: bool


    outline_checker_agent = Agent(
        name="outline_checker_agent",
        instructions="Read the given story outline, and judge the quality. Also, determine if it is a scifi story.",
        output_type=OutlineCheckerOutput,
        model=model
    )

    story_agent = Agent(
        name="story_agent",
        instructions="Write a short story based on the given outline.",
        output_type=str,
        model=model
    )

    # 1. Generate an outline
    outline_result = await Runner.run(
        story_outline_agent,
        input,
    )
    print("Outline generated")

    # 2. Check the outline
    outline_checker_result = await Runner.run(
        outline_checker_agent,
        outline_result.final_output,
    )

    # 3. Add a gate to stop if the outline is not good quality or not a scifi story
    assert isinstance(outline_checker_result.final_output, OutlineCheckerOutput)
    if not outline_checker_result.final_output.good_quality:
        print("Outline is not good quality, so we stop here.")
        raise UserError("Outline is not good quality, so we stop here.")

    if not outline_checker_result.final_output.is_scifi:
        print("Outline is not a scifi story, so we stop here.")
        raise UserError("Outline is not a scifi story, so we stop here.")

    print("Outline is good quality and a scifi story, so we continue to write the story.")

    # 4. Write the story
    story_result = await Runner.run(
        story_agent,
        outline_result.final_output,
    )
    print(f"Story: {story_result.final_output}")
   
    return story_result.final_output
