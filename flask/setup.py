from setuptools import setup, find_packages

setup(
    name='decipher-sdk',
    version='0.0.17',
    package_dir={'': 'src'},
    packages=find_packages(where='src'),
    install_requires=[
        'Flask',
        'requests',
    ],
    author='Decipher AI, Inc',
    author_email='michael@getdecipher.com',
    description='Flask SDK for Decipher AI',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
)