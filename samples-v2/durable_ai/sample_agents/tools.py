from agents import Agent, Runner

async def run(input, model, tools):
    agent = Agent(
        name="Hello world",
        instructions="You are a helpful agent.",
        model=model,
        tools=tools,
    )

    result = await Runner.run(agent, input=input)
    print(result.final_output)

    return result.final_output
