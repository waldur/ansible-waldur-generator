from dataclasses import dataclass

from ansible_waldur_generator.models import BaseGenerationContext


@dataclass
class FactsGenerationContext(BaseGenerationContext):
    resource_type: str
    runner_context_string: str
