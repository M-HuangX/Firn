"""Allow ``python -m src`` to run the analysis agent."""

from dotenv import load_dotenv

load_dotenv()  # must run before any module reads os.getenv()

from src.main import main  # noqa: E402

main()
