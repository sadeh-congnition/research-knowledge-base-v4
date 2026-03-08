import djclick as click


@click.command()
def command() -> None:
    """Launch the Research Knowledge Base TUI."""
    from kb.tui.app import ResearchKBApp

    app = ResearchKBApp()
    app.run()
