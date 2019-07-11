import setuptools

with open("./README.md", "r") as fh:
    long_description = fh.read()

setuptools.setup(
    name="website",
    version="0.0.1",
    author="Grusirna",
    author_email="grusirna@163.com",
    description="django admin website",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/grusirna/website",
    packages=setuptools.find_packages(),
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    zip_safe=False
)
