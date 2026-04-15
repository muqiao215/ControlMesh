"""Docker extras registry and Dockerfile generation for optional sandbox packages."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class DockerExtra:
    """Definition of an optional Docker sandbox package bundle."""

    id: str
    name: str
    description: str
    category: str
    size_estimate: str
    pip_packages: list[str] = field(default_factory=list)
    apt_packages: list[str] = field(default_factory=list)
    depends_on: list[str] = field(default_factory=list)
    build_timeout_extra: int = 0


# Ordered category list for consistent UI rendering.
EXTRA_CATEGORIES: tuple[str, ...] = (
    "Audio / Speech",
    "Vision / OCR",
    "Document Processing",
    "Scientific / Data",
    "ML Frameworks",
    "Web / Browser",
)

DOCKER_EXTRAS: tuple[DockerExtra, ...] = (
    # -- Audio / Speech --
    DockerExtra(
        id="ffmpeg",
        name="FFmpeg",
        description="Convert and process audio/video files (needed for voice messages)",
        category="Audio / Speech",
        size_estimate="~100 MB",
        apt_packages=["ffmpeg"],
    ),
    DockerExtra(
        id="whisper",
        name="Faster Whisper",
        description="Transcribe Telegram voice messages locally to text",
        category="Audio / Speech",
        size_estimate="~500 MB",
        pip_packages=["faster-whisper"],
        depends_on=["ffmpeg"],
        build_timeout_extra=120,
    ),
    # -- Vision / OCR --
    DockerExtra(
        id="opencv",
        name="OpenCV",
        description="Analyze images, screenshots, and diagrams",
        category="Vision / OCR",
        size_estimate="~100 MB",
        pip_packages=["opencv-python-headless"],
        build_timeout_extra=30,
    ),
    DockerExtra(
        id="tesseract",
        name="Tesseract OCR",
        description="Extract text from images and screenshots (fast, lightweight)",
        category="Vision / OCR",
        size_estimate="~40 MB",
        pip_packages=["pytesseract"],
        apt_packages=["tesseract-ocr"],
    ),
    DockerExtra(
        id="easyocr",
        name="EasyOCR",
        description="AI-powered text recognition from images (more accurate than Tesseract)",
        category="Vision / OCR",
        size_estimate="~2.5 GB",
        pip_packages=["easyocr"],
        depends_on=["pytorch-cpu"],
        build_timeout_extra=180,
    ),
    # -- Document Processing --
    DockerExtra(
        id="pymupdf",
        name="PyMuPDF",
        description="Read, search, and extract text from PDF files",
        category="Document Processing",
        size_estimate="~50 MB",
        pip_packages=["pymupdf"],
    ),
    DockerExtra(
        id="pandoc",
        name="Pandoc",
        description="Convert between document formats (Markdown, HTML, DOCX, ...)",
        category="Document Processing",
        size_estimate="~80 MB",
        pip_packages=["pypandoc"],
        apt_packages=["pandoc"],
    ),
    # -- Scientific / Data --
    DockerExtra(
        id="scipy",
        name="SciPy",
        description="Scientific computing, math, and signal processing",
        category="Scientific / Data",
        size_estimate="~130 MB",
        pip_packages=["scipy"],
        build_timeout_extra=60,
    ),
    DockerExtra(
        id="pandas",
        name="pandas",
        description="Work with CSV, Excel, and tabular data",
        category="Scientific / Data",
        size_estimate="~60 MB",
        pip_packages=["pandas"],
        build_timeout_extra=30,
    ),
    DockerExtra(
        id="matplotlib",
        name="Matplotlib",
        description="Generate charts, plots, and visualizations",
        category="Scientific / Data",
        size_estimate="~60 MB",
        pip_packages=["matplotlib"],
        build_timeout_extra=30,
    ),
    # -- ML Frameworks --
    DockerExtra(
        id="pytorch-cpu",
        name="PyTorch (CPU)",
        description="Run ML models locally (CPU-only, no GPU needed)",
        category="ML Frameworks",
        size_estimate="~800 MB",
        pip_packages=[
            "torch",
            "torchaudio",
            "torchvision",
            "--index-url",
            "https://download.pytorch.org/whl/cpu",
        ],
        build_timeout_extra=180,
    ),
    DockerExtra(
        id="transformers",
        name="HF Transformers",
        description="Run Hugging Face models (NLP, sentiment analysis, summarization)",
        category="ML Frameworks",
        size_estimate="~2 GB",
        pip_packages=["transformers", "tokenizers"],
        depends_on=["pytorch-cpu"],
        build_timeout_extra=120,
    ),
    # -- Web / Browser --
    DockerExtra(
        id="playwright",
        name="Playwright",
        description="Automate browsers, take screenshots, scrape web pages",
        category="Web / Browser",
        size_estimate="~450 MB",
        pip_packages=["playwright"],
        build_timeout_extra=120,
    ),
)

DOCKER_EXTRAS_BY_ID: dict[str, DockerExtra] = {e.id: e for e in DOCKER_EXTRAS}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def resolve_extras(selected_ids: list[str]) -> list[DockerExtra]:
    """Resolve *selected_ids* to extras including transitive dependencies.

    Returns a topologically-ordered list (dependencies before dependents).
    Unknown IDs are silently ignored for forward-compatibility.
    """
    resolved_ids: list[str] = []
    seen: set[str] = set()

    def _walk(extra_id: str) -> None:
        if extra_id in seen:
            return
        seen.add(extra_id)
        extra = DOCKER_EXTRAS_BY_ID.get(extra_id)
        if extra is None:
            return
        for dep_id in extra.depends_on:
            _walk(dep_id)
        resolved_ids.append(extra_id)

    for eid in selected_ids:
        _walk(eid)

    return [DOCKER_EXTRAS_BY_ID[eid] for eid in resolved_ids]


def extras_for_display() -> list[tuple[str, list[DockerExtra]]]:
    """Return extras grouped by category in display order."""
    by_cat: dict[str, list[DockerExtra]] = {}
    for extra in DOCKER_EXTRAS:
        by_cat.setdefault(extra.category, []).append(extra)
    return [(cat, by_cat[cat]) for cat in EXTRA_CATEGORIES if cat in by_cat]


def calculate_build_timeout(extras: list[DockerExtra], base: int = 300) -> int:
    """Return total build timeout in seconds."""
    return base + sum(e.build_timeout_extra for e in extras)


def generate_dockerfile_extras(base_content: str, extras: list[DockerExtra]) -> str:
    """Append ``RUN`` instructions for *extras* to the base Dockerfile content.

    Groups apt and pip installs for layer efficiency.  Packages that require a
    custom ``--index-url`` (e.g. PyTorch CPU) get a separate ``RUN`` command.
    """
    if not extras:
        return base_content

    all_apt: list[str] = []
    # pip packages grouped by index-url (None = default PyPI).
    pip_groups: dict[str | None, list[str]] = {}

    for extra in extras:
        all_apt.extend(extra.apt_packages)
        _collect_pip(extra.pip_packages, pip_groups)

    lines: list[str] = [
        base_content.rstrip(),
        "",
        "# -- Docker extras (auto-generated) --",
        "",
        "USER root",
    ]

    if all_apt:
        apt_joined = " ".join(sorted(set(all_apt)))
        lines.append(
            f"RUN apt-get update \\\n"
            f"    && apt-get install -y --no-install-recommends {apt_joined} \\\n"
            f"    && rm -rf /var/lib/apt/lists/*"
        )

    # Install packages with custom index URLs FIRST (e.g. PyTorch CPU) so
    # that later packages (easyocr, transformers) find the CPU-only version
    # instead of pulling the full CUDA variant from PyPI.
    has_custom_index = any(url is not None for url in pip_groups)
    for index_url in sorted(pip_groups, key=lambda u: (u is None, u or "")):
        pkgs = pip_groups[index_url]
        pkg_joined = " ".join(pkgs)
        if index_url:
            lines.append(f"RUN pip install --no-cache-dir {pkg_joined} --index-url {index_url}")
        elif has_custom_index:
            # Pin packages from custom indexes via pip freeze so the standard
            # PyPI install cannot upgrade them (prevents e.g. torch CPU being
            # replaced by the full CUDA variant through transitive deps).
            lines.append(
                f"RUN pip freeze > /tmp/idx-constraints.txt \\\n"
                f"    && pip install --no-cache-dir -c /tmp/idx-constraints.txt {pkg_joined} \\\n"
                f"    && rm -f /tmp/idx-constraints.txt"
            )
        else:
            lines.append(f"RUN pip install --no-cache-dir {pkg_joined}")

    lines.append("")
    lines.append("USER node")
    lines.append("")

    return "\n".join(lines)


def _collect_pip(
    pip_packages: list[str],
    groups: dict[str | None, list[str]],
) -> None:
    """Parse pip_packages list, splitting out ``--index-url`` into groups."""
    index_url: str | None = None
    regular: list[str] = []

    i = 0
    while i < len(pip_packages):
        if pip_packages[i] == "--index-url" and i + 1 < len(pip_packages):
            index_url = pip_packages[i + 1]
            i += 2
        else:
            regular.append(pip_packages[i])
            i += 1

    if regular:
        groups.setdefault(index_url, []).extend(regular)
