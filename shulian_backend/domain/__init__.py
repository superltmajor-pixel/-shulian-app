"""数恋后端领域层。"""

from .character_bible import (
    CharacterBible,
    CharacterBibleEntry,
    CharacterBibleError,
    CharacterBibleSource,
)
from .content_cues import EXPLICIT_CONTENT_CUES
from .errors import (
    AIConfigServiceError,
    InvalidStateDataError,
    StateServiceError,
    StateUnavailableError,
    TTSConfigurationError,
    TTSServiceError,
)
from .live_status_tones import DEFAULT_TONE_COLOR, LIVE_STATUS_TONES, tone_color
from .personality import (
    BehaviorAnchor,
    CharacterOutputRail,
    DialogueExample,
    PersonalityProfile,
    PersonalityProfileError,
    SourcedPersonalityStatement,
)
from .relationship_levels import (
    GUARD_COMMITMENT_LEVEL,
    GUARD_STAGE_LEVEL,
    LEVEL_LIFELONG,
    LEVEL_MUTUAL_AFFECTION,
    LEVEL_SHARED_FUTURE,
)
from .reply_motifs import REPEAT_ENDING_MOTIFS, REPEAT_MOTIFS
from .runtime import MediaContext, RoleLibraryContext, RuntimeContext

__all__ = [
    "AIConfigServiceError",
    "BehaviorAnchor",
    "CharacterBible",
    "CharacterBibleEntry",
    "CharacterBibleError",
    "CharacterBibleSource",
    "CharacterOutputRail",
    "DEFAULT_TONE_COLOR",
    "DialogueExample",
    "EXPLICIT_CONTENT_CUES",
    "GUARD_COMMITMENT_LEVEL",
    "GUARD_STAGE_LEVEL",
    "InvalidStateDataError",
    "LEVEL_LIFELONG",
    "LEVEL_MUTUAL_AFFECTION",
    "LEVEL_SHARED_FUTURE",
    "LIVE_STATUS_TONES",
    "MediaContext",
    "PersonalityProfile",
    "PersonalityProfileError",
    "REPEAT_ENDING_MOTIFS",
    "REPEAT_MOTIFS",
    "RoleLibraryContext",
    "RuntimeContext",
    "SourcedPersonalityStatement",
    "StateServiceError",
    "StateUnavailableError",
    "TTSConfigurationError",
    "TTSServiceError",
    "tone_color",
]
