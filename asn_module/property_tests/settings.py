import os

from hypothesis import HealthCheck
from hypothesis import settings as hypothesis_settings

PROFILE = os.getenv("HYPOTHESIS_PROFILE", "ci")

hypothesis_settings.register_profile(
	"ci",
	max_examples=80,
	deadline=None,
	suppress_health_check=(HealthCheck.too_slow,),
)
hypothesis_settings.register_profile(
	"local",
	max_examples=300,
	deadline=None,
)
hypothesis_settings.load_profile(PROFILE)
