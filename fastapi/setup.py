from setuptools import setup, find_packages

setup(
    name='decipher_sdk',
    version='0.1.0',
    author='Your Name',
    author_email='your.email@example.com',
    description='A FastAPI SDK for error monitoring and logging.',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    package_dir={'': 'src'},
    packages=find_packages(where='src'),
    install_requires=[
        'fastapi',  # This implicitly includes starlette
        'requests'  # For HTTP requests
    ],
    python_requires='>=3.7',
)