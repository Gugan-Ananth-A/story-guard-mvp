"""Command line entry. Later slices add generate on this command."""

from story_guard.graph import run


def main() -> int:
    state = run()
    print(f"graph={state['graph']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
