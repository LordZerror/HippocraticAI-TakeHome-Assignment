import sys
from story_engine import (
    ChunkResult,
    create_opening_chunk,
    create_next_chunk
)

LINE  = "─" * 62
DLINE = "═" * 62
MOON  = "🌙"
BOOK  = "📖"
STAR  = "✨"
PEN   = "✏️ "
ZZZ   = "💤"

def header() -> None:
    print(DLINE)
    print(f"\t{MOON}  Bedtime Story Teller  {MOON}")
    print(DLINE)
    print()

def print_arc_summary(result: ChunkResult) -> None:
    arc = result.arc
    print(f"  Category  : {arc.category.upper()}")
    print(f"  Title     : {arc.title}")
    print(f"  Setting   : {arc.setting}")
    print(f"  Strategy  : {arc.strategy_hint}")
    print(f"  Structure : {arc.total_chunks} parts planned")
    if arc.characters:
        print("  Cast      :")
        for c in arc.characters:
            print(f"    • {c}")
    print(LINE)

def print_chunk(result: ChunkResult, verbose: bool = False) -> None:
    arc      = result.arc
    position = _position_label(result.chunk_num, arc.total_chunks)

    print()
    print(f"{BOOK}  Part {result.chunk_num} of {arc.total_chunks}  ·  {position}")
    print(LINE)
    print()
    print(result.chunk)
    print()
    print(LINE)

    j = result.judgment
    if verbose and j:
        age  = j.get("age_fit",      {})
        eng  = j.get("engagement",   {})
        arc_ = j.get("arc_fidelity", {})
        avg  = _avg_score(age, eng, arc_)
        approved = j.get("approved", True)
        tag  = "✅ approved" if approved else "🔁 rewritten"
        print(f"  Quality: age-fit {age.get('score','?')}/10 · "
                f"engagement {eng.get('score','?')}/10 · "
                f"arc-fidelity {arc_.get('score','?')}/10 · "
                f"avg {avg:.1f}/10  [{tag}]")
        print()
    else:
        score = _avg_score(
            j.get("age_fit", {}), j.get("engagement", {}), j.get("arc_fidelity", {})
        )
        print(f"  Story quality: {score:.0f}/10")
        print()

def _avg_score(*axis_dicts) -> float:
    scores = [d.get("score", 7) for d in axis_dicts if isinstance(d, dict)]
    return sum(scores) / len(scores) if scores else 7.0

def _position_label(chunk_num: int, total: int) -> str:
    labels = {
        "setup":         "Act I  — Setup",
        "rising_action": "Act II — Rising Action",
        "climax":        "Act II — Climax",
        "resolution":    "Act III — Resolution",
    }
    from story_engine import _arc_position_label
    return labels.get(_arc_position_label(chunk_num, total), "")

def ask(prompt: str, allow_empty: bool = False) -> str:
    while True:
        val = input(prompt).strip()
        if val or allow_empty:
            return val
        print("  (Please type something)")

def ask_verbose() -> bool:
    ans = input("  Show quality scores after each part? (y/n, default n): ").strip().lower()
    return ans == "y"

def ask_direction(options: list[str]) -> tuple[str | None, bool]:
    print()
    print(f"  How should the story continue?")
    print()
    for i, opt in enumerate(options, 1):
        print(f"  {i}. {opt}")
    print(f"  {len(options)+1}. {PEN} Write your own direction")
    print(f"  {len(options)+2}. {ZZZ}  End the story here")
    print()

    while True:
        raw = input("  Your choice: ").strip()

        if raw.isdigit():
            n = int(raw)
            if 1 <= n <= len(options):
                return options[n - 1], False
            if n == len(options) + 1:
                custom = ask("  Describe where the story goes:\n  > ")
                return custom, False
            if n == len(options) + 2:
                return None, True

        if raw:
            print(f'  Using "{raw}" as the direction.')
            return raw, False

        print("  Please enter a number or type a direction.")

def ask_feedback() -> str | None:
    print(f"  (Optional) Any feedback on this part? Press Enter to skip.")
    fb = input("  Feedback: ").strip()
    return fb if fb else None

def main() -> None:
    header()
    print("  What kind of bedtime story would you like?")
    print("  Describe your idea about characters, setting, mood or anything!")
    print()
    request = ask("  > ")
    verbose = ask_verbose()
    print()

    print(f"  {STAR} Planning your story …")
    result = create_opening_chunk(request)

    print()
    print(DLINE)
    print(f"  {MOON}  \"{result.arc.title}\"")
    print(DLINE)
    print_arc_summary(result)

    print_chunk(result, verbose)

    if result.is_final:
        print(f"  {MOON}  The End. Sweet dreams!  {MOON}")
        print()
        return

    arc     = result.arc
    bible   = result.bible
    history = [result.chunk]
    chunk_num = 2

    while True:
        feedback = ask_feedback()

        direction, is_ending = ask_direction(result.options)

        if feedback and direction:
            direction = f"{direction}\n\nUser feedback on previous part: {feedback}"
        elif feedback:
            direction = f"User feedback on previous part: {feedback}"

        print()
        print(f"  {STAR} Writing part {chunk_num} …")

        result = create_next_chunk(
            request   = request,
            arc       = arc,
            bible     = bible,
            history   = history,
            direction = direction or "",
            chunk_num = chunk_num,
            is_ending = is_ending,
        )

        # Update shared state
        bible   = result.bible
        history.append(result.chunk)

        print_chunk(result, verbose)

        if result.is_final:
            print(f"  {MOON}  The End. Sweet dreams!  {MOON}")
            print()
            break

        chunk_num += 1

        if chunk_num > arc.total_chunks and not result.is_final:
            print("  The story has reached its planned length.")
            wrap = input("  Wrap it up now? (y/n): ").strip().lower()
            if wrap == "y":
                is_ending = True
                print(f"\n  {STAR} Writing the ending …")
                result = create_next_chunk(
                    request=request, arc=arc, bible=bible,
                    history=history, direction="", chunk_num=chunk_num,
                    is_ending=True,
                )
                bible = result.bible
                history.append(result.chunk)
                print_chunk(result, verbose)
                print(f"  {MOON}  The End. Sweet dreams!  {MOON}")
                print()
                break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n\n  Goodnight! {MOON}\n")
        sys.exit(0)
