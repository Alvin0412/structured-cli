from setuptools import find_namespace_packages, setup


setup(
    name="cli-anything-structured",
    version="0.1.0",
    description="Structured Web CLI harness for AI agents",
    license="MIT",
    packages=find_namespace_packages(include=["cli_anything.*"]),
    include_package_data=True,
    package_data={
        "cli_anything.structured": ["README.md", "skills/SKILL.md"],
    },
    install_requires=[
        "click>=8.1,<9",
        "mcp>=1.26,<2",
        "websocket-client>=1.8,<2",
    ],
    entry_points={
        "console_scripts": [
            "cli-anything-structured=cli_anything.structured.structured_cli:main",
            "structured-mcp=cli_anything.structured.mcp_server:main",
        ]
    },
)
