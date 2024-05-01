from setuptools import setup, find_packages

setup(
    name='decipher_sdk_fastapi',
    version='0.0.22',
    author='Decipher AI',
    author_email='help@getdecipher.com',
    description='A FastAPI SDK for error monitoring and logging.',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    package_dir={'': 'src'},
    packages=find_packages(where='src'),
    install_requires=[
        'fastapi',  
        'requests' 
    ],
    python_requires='>=3.7',
)