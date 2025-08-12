from agents import Agent, Runner
from agents.run import Model

async def run(input: str, model: Model) -> str:
    agent = Agent(
        name="Assistant",
        instructions="You only respond in haikus.",
        model=model
    )

    result = await Runner.run(
        agent,
        input=input
    )
    
    return result.final_output
