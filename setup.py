import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="pal3thorn/director",
    version="1.2.3",
    author="David Cavar",
    author_email="wizzard405@gmail.com",
    description="Module for automated remote management",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Palethorn/director",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.6',
)