from agents import Agent, Runner, function_tool
from openai import BaseModel

class Weather(BaseModel):
    city: str
    temperature_range: str
    conditions: str

@function_tool
def get_weather(city: str) -> Weather:
    print("[debug] get_weather called")
    return Weather(city=city, temperature_range="14-20C", conditions="Sunny with wind.")

async def run(input, model):
    agent = Agent(
        name="Hello world",
        instructions="You are a helpful agent.",
        model=model,
        tools=[get_weather],
    )

    result = await Runner.run(agent, input=input)
    print(result.final_output)

    return result.final_output
