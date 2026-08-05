class BaseAgent:
    def __init__(self, name: str, role: str):
        self.name = name
        self.role = role

    def process(self, input_data: dict) -> dict:
        raise NotImplementedError("Each agent must implement process()")
