from setuptools import setup, find_packages


setup(name='uartz',
      version="0.1",
      author="Mike Spindel",
      author_email="mike@spindel.is",
      license="MIT",
      description="",
      keywords="",
      scripts=["bin/uartz"],
      packages=find_packages(exclude=['ez_setup']),
      zip_safe=False,
      classifiers=[
          "Development Status :: 4 - Beta",
          "License :: OSI Approved :: MIT License",
          "Operating System :: MacOS :: MacOS X",
          "Intended Audience :: Developers",
          "Natural Language :: English",
          "Programming Language :: Python"])
