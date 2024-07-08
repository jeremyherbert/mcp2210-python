import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="mcp2210-python",
    version="1.0.5",
    author="Jeremy Herbert",
    author_email="jeremy.006@gmail.com",
    description="A python driver for the MCP2210 USB-to-SPI converter",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/jeremyherbert/mcp2210-python",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires=['hidapi'],
    python_requires='>=3.6',
)
