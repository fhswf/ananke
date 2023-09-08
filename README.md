# Ananke Jupyter Distribution

The Ananke project provides preconfigured [JupyterHub](https://jupyter.org/hub) images for [Podman](https://podman.io) (a [Docker](https://www.docker.com)-like containerization tool) with a focus on integrating [JupyterLab](https://jupyter.org) and [nbgrader](https://nbgrader.readthedocs.io) into learning management systems (LMS) like [Moodle](https://moodle.org), [Canvas](https://www.instructure.com/canvas) and many other.

The project's core is the Kore service providing GUI based course management and an [LTI 1.3](https://en.wikipedia.org/wiki/Learning_Tools_Interoperability) interface for nbgrader.

Target group are administrators of small to medium sized JupyterHubs used in teaching environments with a handfull of courses. The project's focus is not on large-scale JupyterHubs with thousands of users but on:
* easy setup and operation for instructors and students,
* advice and preconfiguration for administrators,
* flexibility to implement different application scenarios.

Also have a look at [Ananke website](https://gauss.fh-zwickau.de/ananke).

## Overall architecture

The structure of an Ananke based JupyterHub deployment is as follows:
* A host machine runs one or several Podman containers.
* Each container represents one JupyterHub, which may be used by a whole university or a department or by only one intructor depending on individual configuration needs. One host machine may provide several JupyterHubs with different configurations and features.
* Each JupyterHub provides individual JupyterLabs for all its users (instructors and students).

## Available container images

The Ananke project uses [Podman](https://podman.io) for containerization. Podman is free, open source, and compatible with [Docker](https://www.docker.com). See [](why-podman) for details on why we use Podman.

Following container images are provided by the Ananke project:
* `ananke-base` (JupyterHub with LTI login and nbgitpuller)
* `ananke-nbgrader` (like `ananke-base` plus LTI integrated nbgrader)

## Documentation

See `doc` subdirectory. There's also an [HTML rendering of the doc](https://gauss.fh-zwickau.de/ananke/doc).

## Contact and contributors

The Ananke project started as a joint project of [Leipzig University of Applied Sciences](https://www.htwk-leipzig.de/en/htwk-leipzig) and [Zwickau University of Applied Sciences](https://www.fh-zwickau.de/english/).

The project team currently consists of:
* [Jens Flemming](https://www.fh-zwickau.de/~jef19jdw)
* [Konrad Schöbel](https://fdit.htwk-leipzig.de/fakultaet-dit/personen/professoren/prof-dr-konrad-schoebel)
* [Marcus Wittig](https://www.fh-zwickau.de/?id=5361)
