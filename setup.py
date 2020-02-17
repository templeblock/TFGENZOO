import setuptools

setuptools.setup(
    name='TFGENZOO',
    packages=setuptools.find_packages(),
    install_requires=['tensorflow>=2.1.0', 'tensorflow_probability>=0.9.0'],
    version='0.1.0alpha',
    author='MokkeMeguru',
    author_email='meguru.mokke@gmail.com',
    description='helper of building generative model with Tensorflow 2.x',
    long_description=('heavily documented (test and description and formula)'
                      + 'generative model examples / layers'),
    long_description_content_type='text/markdown',
    url='https://github.com/MokkeMeguru/TFGENZOO',
    licence='MIT',
    classifiers=[
        "Programming Language :: Python :: 3.7.6",
        "Licence :: OSI Apprived :: MIT Licence",
        "Operation System :: Linux, Windows",
    ]
)