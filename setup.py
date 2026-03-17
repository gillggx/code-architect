from setuptools import setup, find_packages

setup(
    name="architect-agent",
    version="0.1.0",
    description="Multi-language code architecture analyzer with persistent memory",
    python_requires=">=3.11",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        line.strip()
        for line in open("requirements.txt")
        if line.strip() and not line.startswith("#")
    ],
    extras_require={
        "dev": ["pytest", "pytest-asyncio", "pytest-cov", "black", "flake8", "mypy"],
    },
)
