REST API
========
EOS has a REST API to control the orchestrator.
Example functions include:

* Submit tasks, experiments, and campaigns, as well as cancel them
* Load, unload, and reload experiments and laboratories
* Get the status of tasks, experiments, and campaigns
* List experiments with optional filters to retrieve experiment IDs
* Download task output files

.. warning::

    Be careful about who accesses the REST API.
    The REST API currently has no authentication.

    Only use it internally in its current state.
    If you need to make it accessible over the web use a VPN and set up a firewall.

.. warning::

    EOS will likely have control over expensive (and potentially dangerous) hardware and unchecked REST API access could
    have severe consequences.

Documentation
-------------
The REST API is documented using `OpenAPI <https://swagger.io/specification/>`_ and can be accessed at:

.. code-block:: bash

    http://localhost:8070/docs

or whatever host and port you have configured for the REST API server.
