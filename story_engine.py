import os
import json
import openai
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

def _call(
    user_prompt: str,
    system_prompt: str,
    max_tokens: int = 600,
    temperature: float = 0.75,
) -> str:
    openai.api_key = os.getenv("OPENAI_API_KEY")
    resp = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": user_prompt},
        ],
        stream=False,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return resp.choices[0].message["content"]  # type: ignore


def _parse_json(raw: str) -> dict:
    """Strip markdown fences and parse JSON. Returns {} on failure."""
    clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        return json.loads(clean)
    except json.JSONDecodeError:
        return {}


STORY_CATEGORIES = [
    "adventure", "friendship", "funny", 
    "mystery", "fantasy", "nature"
]


@dataclass
class StoryArc:
    category:      str
    strategy_hint: str
    title:         str
    setting:       str
    characters:    list[str]
    acts:          dict = field(default_factory=dict)
    total_chunks:  int = 4


@dataclass
class StoryBible:
    """
    Serves as persistent history for the LLM to refer to 
    """
    characters: dict[str, str] = field(default_factory=dict) 
    settings:   list[str]      = field(default_factory=list) 
    threads:    list[str]      = field(default_factory=list) 
    resolved:   list[str]      = field(default_factory=list) 

    def as_text(self) -> str:
        if not self.characters and not self.threads:
            return "(story has not started yet)"
        lines = []
        if self.characters:
            lines.append("Characters:")
            for name, desc in self.characters.items():
                lines.append(f"  • {name}: {desc}")
        if self.settings:
            lines.append("Locations visited: " + ", ".join(self.settings))
        if self.threads:
            lines.append("Open plot threads:")
            for t in self.threads:
                lines.append(f"  • {t}")
        if self.resolved:
            lines.append("Resolved: " + "; ".join(self.resolved))
        return "\n".join(lines)

_CLASSIFIER_SYSTEM = f"""You are a children's story editor. Given a story request, classify it into
exactly one category from this list: {', '.join(STORY_CATEGORIES)}.

Then write one sentence of STRATEGY ADVICE for how to craft this specific story well
(e.g. pacing, emotional beats, the kind of humor, the level of wonder, etc.).

Respond ONLY with valid JSON — no markdown, no extra text:
{{
  "category": "<one of the listed categories>",
  "strategy": "<one sentence of craft advice tailored to this request>"
}}"""


def classify(request: str) -> tuple[str, str]:
    """Agent 1. Returns (category, strategy_hint)."""
    raw  = _call(request, _CLASSIFIER_SYSTEM, max_tokens=120, temperature=0.3) #temperature=0.3 - decisive, consistent classification not creativity
    data = _parse_json(raw)
    return (
        data.get("category", "adventure"),
        data.get("strategy", "Keep the language simple, warm, and full of wonder."),
    )
    
# Forms the 3-part story of the same

_ARC_SYSTEM = """You are a children's book story structure expert.
Given a story request and a category, design a tight 3-act structure for a short bedtime story
(ages 5–10). The structure must match the category's craft demands.

Respond ONLY with valid JSON:
{
  "title":      "<short evocative title>",
  "setting":    "<one sentence describing the world>",
  "characters": ["<name>: <one-line description>", ...],
  "acts": {
    "setup":         "<what the opening chunk establishes — character + desire + world>",
    "rising_action": "<the challenge, journey, or mystery that unfolds>",
    "climax":        "<the turning point — a decision, discovery, or small act of courage>",
    "resolution":    "<the warm, cozy landing appropriate for bedtime>"
  },
  "total_chunks": <integer between 4 and 6>
}"""


def plan_arc(request: str, category: str, strategy: str) -> StoryArc:
    """Agent 2. Produces a StoryArc that all subsequent agents reference."""
    prompt = (
        f"Story request: {request}\n"
        f"Category: {category}\n"
        f"Craft strategy to follow: {strategy}"
    )
    raw  = _call(prompt, _ARC_SYSTEM, max_tokens=500, temperature=0.6)
    data = _parse_json(raw)

    return StoryArc(
        category      = category,
        strategy_hint = strategy,
        title         = data.get("title", "A Bedtime Story"),
        setting       = data.get("setting", ""),
        characters    = data.get("characters", []),
        acts          = data.get("acts", {}),
        total_chunks  = max(4, min(6, data.get("total_chunks", 4))),
    )

_STORYTELLER_SYSTEM = """You are a warm, imaginative bedtime storyteller for children ages 5–10.

Your writing rules:
- Simple but vivid language — no words a 6-year-old would not know
- 3–4 short paragraphs per chunk, paced for reading aloud
- Match the genre strategy you are given
- Stay faithful to the arc position you are given (setup / rising action / climax / resolution)
- Only use characters and settings from the continuity bible unless adding one is unavoidable
- Tone: calm, cozy, wonder-filled — appropriate for winding down at bedtime
- Never include violence, fear, or adult themes"""


def _arc_position_label(chunk_num: int, total_chunks: int) -> str:
    """Map chunk number to the narrative act it should serve."""
    if chunk_num == 1:
        return "setup"
    if chunk_num >= total_chunks:
        return "resolution"
    midpoint = total_chunks // 2 + 1
    if chunk_num >= midpoint:
        return "climax"
    return "rising_action"


def generate_chunk(
    request:   str,
    arc:       StoryArc,
    bible:     StoryBible,
    history:   list[str],
    direction: str | None,
    chunk_num: int,
) -> str:
    position = _arc_position_label(chunk_num, arc.total_chunks)
    act_goal = arc.acts.get(position, "")

    parts = [
        f"Original story request: {request}",
        f"Story category: {arc.category}",
        f"Craft strategy: {arc.strategy_hint}",
        f"Setting: {arc.setting}",
        "",
        f"ARC POSITION: {position.upper().replace('_', ' ')}",
        f"What this chunk must accomplish: {act_goal}",
        "",
        "CONTINUITY BIBLE (respect everything listed here):",
        bible.as_text(),
    ]

    if history:
        parts += ["", "Story so far (last chunk):", history[-1]]
        if direction:
            parts += ["", f"User chose this direction: {direction}"]
        parts += ["", "Continue the story, serving the arc position above."]
    else:
        parts += ["", "Begin the story now, establishing the setup."]

    return _call("\n".join(parts), _STORYTELLER_SYSTEM, max_tokens=550, temperature=0.85) # high enough for vivid prose generation

_JUDGE_SYSTEM = """You are a children's literature editor. Evaluate the given story chunk on THREE axes.
Be honest and specific — do not be lenient.

Respond ONLY with valid JSON:
{
  "age_fit":      { "score": <1–10>, "note": "<specific issue if score < 7, else empty string>" },
  "engagement":   { "score": <1–10>, "note": "<specific issue if score < 7, else empty string>" },
  "arc_fidelity": { "score": <1–10>, "note": "<specific issue if score < 7, else empty string>" },
  "approved":     <true if ALL three scores >= 7, else false>,
  "rewrite_note": "<single concrete instruction for improvement; empty string if approved>"
}"""


def judge_chunk(chunk: str, arc: StoryArc, position: str) -> dict:
    """Agent 4. Returns the full judgment dict."""
    prompt = (
        f"Story category: {arc.category}\n"
        f"Arc position this chunk must serve: {position}\n"
        f"What this position requires: {arc.acts.get(position, '')}\n\n"
        f"Chunk to evaluate:\n{chunk}"
    )
    raw  = _call(prompt, _JUDGE_SYSTEM, max_tokens=260, temperature=0.2) # consistent, critical judgment, not creative leniency
    data = _parse_json(raw)
    if "approved" not in data:
        data["approved"] = True  # graceful fallback — never block on a bad parse
    return data

_CONTINUITY_SYSTEM = """You are a story continuity editor for a serialised children's bedtime story.
After reading one new chunk, extract ONLY what is NEW or CHANGED since the previous bible.

Respond ONLY with valid JSON:
{
  "new_characters":  { "<name>": "<one-line description>" },
  "new_settings":    ["<location name>"],
  "opened_threads":  ["<brief description of new unresolved plot thread>"],
  "closed_threads":  ["<brief description of thread resolved in this chunk>"]
}"""


def update_bible(bible: StoryBible, chunk: str) -> StoryBible:
    """Agent 5. Mutates and returns the StoryBible with deltas from `chunk`."""
    raw  = _call(chunk, _CONTINUITY_SYSTEM, max_tokens=200, temperature=0.2) # temperature = 0.2 extraction, not creativity
    data = _parse_json(raw)

    for name, desc in data.get("new_characters", {}).items():
        bible.characters[name] = desc

    for loc in data.get("new_settings", []):
        if loc not in bible.settings:
            bible.settings.append(loc)

    bible.threads  += [t for t in data.get("opened_threads", []) if t not in bible.threads]
    bible.resolved += [t for t in data.get("closed_threads",  []) if t not in bible.resolved]
    bible.threads   = [t for t in bible.threads if t not in bible.resolved]

    return bible

_OPTIONS_SYSTEM = """You are a children's story path designer.
Generate exactly 3 SHORT, vivid continuation options.
Rules:
- Each option is ONE sentence
- Each must be meaningfully different from the others
- Each must respect the open plot threads and characters listed
- Each must naturally move toward the arc's next required position
- Language should excite a 6-year-old
Output ONLY a numbered list — no preamble, no explanation:
1. <option>
2. <option>
3. <option>"""


def generate_options(
    request:       str,
    arc:           StoryArc,
    bible:         StoryBible,
    next_position: str,
) -> list[str]:
    """Agent 6. Returns exactly 3 arc-aware options."""
    prompt = (
        f"Story request: {request}\n"
        f"Category: {arc.category}\n"
        f"Next arc position to move toward: {next_position} — {arc.acts.get(next_position, '')}\n\n"
        f"Continuity bible:\n{bible.as_text()}\n\n"
        "Generate 3 ways the story could continue that serve the arc position above."
    )
    raw = _call(prompt, _OPTIONS_SYSTEM, max_tokens=160, temperature=0.9) # High for options to feel fresh and interesting

    options: list[str] = []
    for line in raw.strip().splitlines():
        line = line.strip()
        if line and line[0].isdigit() and "." in line:
            options.append(line.split(".", 1)[1].strip())

    defaults = [
        "A surprising discovery changes everything.",
        "A new friend appears with an unexpected secret.",
        "A gentle challenge reveals hidden bravery.",
    ]
    while len(options) < 3:
        options.append(defaults[len(options)])
    return options[:3]

def _generate_and_judge(
    request:     str,
    arc:         StoryArc,
    bible:       StoryBible,
    history:     list[str],
    direction:   str | None,
    chunk_num:   int,
    max_retries: int = 2,
) -> tuple[str, dict]:
    position = _arc_position_label(chunk_num, arc.total_chunks)
    chunk    = generate_chunk(request, arc, bible, history, direction, chunk_num)
    judgment = judge_chunk(chunk, arc, position)

    for _ in range(max_retries):
        if judgment.get("approved", True):
            break
        note = judgment.get("rewrite_note", "")
        rewrite_direction = f"{direction or ''}\n\nEditor correction: {note}".strip()
        chunk    = generate_chunk(request, arc, bible, history, rewrite_direction, chunk_num)
        judgment = judge_chunk(chunk, arc, position)

    return chunk, judgment

# Setup to be used in app.py
@dataclass
class ChunkResult:
    chunk:     str
    judgment:  dict
    options:   list[str]
    arc:       StoryArc
    bible:     StoryBible
    chunk_num: int
    is_final:  bool


def create_opening_chunk(request: str) -> ChunkResult:
    category, strategy = classify(request)
    arc   = plan_arc(request, category, strategy)
    bible = StoryBible()

    chunk, judgment = _generate_and_judge(request, arc, bible, [], None, 1)
    bible = update_bible(bible, chunk)

    next_pos = _arc_position_label(2, arc.total_chunks)
    options  = generate_options(request, arc, bible, next_pos) if arc.total_chunks > 1 else []

    return ChunkResult(
        chunk=chunk, judgment=judgment, options=options,
        arc=arc, bible=bible, chunk_num=1, is_final=(arc.total_chunks == 1),
    )


def create_next_chunk(
    request:   str,
    arc:       StoryArc,
    bible:     StoryBible,
    history:   list[str],
    direction: str,
    chunk_num: int,
    is_ending: bool = False,
) -> ChunkResult:
    actual_chunk_num = arc.total_chunks if is_ending else chunk_num
    if is_ending:
        direction = (
            "Bring the story to a warm, cozy resolution — "
            "a gentle landing perfect for drifting off to sleep."
        )

    chunk, judgment = _generate_and_judge(
        request, arc, bible, history, direction, actual_chunk_num
    )
    bible    = update_bible(bible, chunk)
    is_final = is_ending or (chunk_num >= arc.total_chunks)

    options: list[str] = []
    if not is_final:
        next_pos = _arc_position_label(chunk_num + 1, arc.total_chunks)
        options  = generate_options(request, arc, bible, next_pos)

    return ChunkResult(
        chunk=chunk, judgment=judgment, options=options,
        arc=arc, bible=bible, chunk_num=actual_chunk_num, is_final=is_final,
    )
