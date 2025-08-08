import azure.functions as func
import durable_ai

# Import the agent runners
import deterministic
import hello_world


app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)
ai_app = durable_ai.DurableAIFunctionApp(app)

ai_app.enable_agent_http_trigger()

@ai_app.agent(name="hello_world")
async def run_hello_world(input):
    return await hello_world.run(input)

@ai_app.agent(name="deterministic")
async def run_deterministic(input):
    return await deterministic.run(input)
