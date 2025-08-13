from agents import Agent, Model, Runner, Tool

async def run(input: str, model: str | Model, tools: list[Tool]) -> str:
    agent = Agent(
        name="Hello world",
        instructions="You are a helpful agent.",
        model=model,
        tools=tools,
    )

    result = await Runner.run(agent, input=input)
    print(result.final_output)

    return result.final_output
