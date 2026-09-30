from setuptools import find_packages, setup


setup(
    name="qshare",
    version="0.3.5",
    description="Quickly share local files through a public TryCloudflare tunnel.",
    author="steinvenic",
    author_email="761701732@qq.com",
    url="https://github.com/steinvenic/qshare",
    package_dir={"": "src"},
    packages=find_packages("src"),
    install_requires=["qrcode==7.3"],
    python_requires=">=3.6",
    entry_points={"console_scripts": ["qshare=qshare.cli:main"]},
)
