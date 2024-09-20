from setuptools import find_packages, setup

setup_args = dict(
    name='kore',
    packages=find_packages(),
    version='0.1.0',
    description="JupyterHub kore lti connector",
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    author="TODO",
    author_email="void@example.com",
    url="https://github.com/fhswf",
    license="MIT",
    python_requires=">=3.10",
    include_package_data=True,
)

setup_args['install_requires'] = install_requires = []
with open('requirements.txt') as f:
    for line in f.readlines():
        req = line.strip()
        if not req or req.startswith(('-e', '#')):
            continue
        install_requires.append(req)

if __name__ == '__main__':
    setup(**setup_args)