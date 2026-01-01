import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Flask
    SECRET_KEY = os.getenv("SECRET_KEY", "REDACTED")

    # MySQL
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "root")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "REDACTED")
    DB_NAME = os.getenv("DB_NAME", "code_share")

    # Uploads
    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, os.getenv("UPLOAD_FOLDER", "uploads"))
    MAX_CONTENT_LENGTH = 40 * 1024 * 1024  # 40MB (same limit as DB constraint)

    ALLOWED_EXTENSIONS = {
        # Archives
        "zip", "rar", "7z", "tar", "gz",

        # Code
        "py", "js", "java", "c", "cpp", "h",
        "html", "css", "json", "xml", "sql",

        # Docs
        "pdf", "doc", "docx", "ppt", "pptx",
        "xls", "xlsx", "txt", "md",

        # Images
        "png", "jpg", "jpeg", "gif", "webp"
    }

    # Cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Project language choices (UI dropdown). Users can also add custom languages.
    # This list is intentionally broad (common languages/DSLs). It is not exhaustive.
    PROJECT_LANGUAGE_CHOICES = [
        # General purpose
        "Python", "JavaScript", "TypeScript", "Java", "C", "C++", "C#", "Go", "Rust",
        "PHP", "Ruby", "Kotlin", "Swift", "Dart", "Scala", "R", "MATLAB", "Perl",
        "Lua", "Haskell", "Elixir", "Erlang", "Clojure", "F#", "OCaml", "Julia",

        # Web / UI
        "HTML", "CSS", "Sass", "Less", "Vue", "React", "Angular", "Svelte",

        # Backend / frameworks
        "Node.js", "Express", "Django", "Flask", "FastAPI", "Spring", ".NET", "Laravel",
        "Rails", "Symfony",

        # Data / query
        "SQL", "PL/SQL", "T-SQL", "GraphQL", "MongoDB", "Redis",

        # Mobile
        "Android", "iOS", "React Native", "Flutter",

        # DevOps / scripting
        "Bash", "PowerShell", "Docker", "Kubernetes", "Terraform", "Ansible",
        "YAML", "JSON",

        # Low-level / systems
        "Assembly", "Embedded C", "Verilog", "VHDL",

        # Other / niche
        "Markdown", "LaTeX", "Solidity", "Prolog", "Groovy", "Smalltalk",
    ]
