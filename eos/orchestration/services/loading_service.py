import traceback

from eos.configuration.configuration_manager import ConfigurationManager
from eos.configuration.exceptions import EosConfigurationError
from eos.containers.container_manager import ContainerManager
from eos.devices.device_manager import DeviceManager
from eos.experiments.entities.experiment import ExperimentStatus
from eos.experiments.experiment_manager import ExperimentManager
from eos.logging.logger import log
from eos.orchestration.exceptions import EosExperimentTypeInUseError
from eos.database.abstract_sql_db_interface import AsyncDbSession
from eos.tasks.entities.task import TaskStatus, Task
from eos.tasks.task_manager import TaskManager
from eos.utils.async_rlock import AsyncRLock
from eos.utils.di.di_container import inject


class LoadingService:
    """Responsible for loading/unloading entities such as labs, experiments, etc."""

    @inject
    def __init__(
        self,
        configuration_manager: ConfigurationManager,
        device_manager: DeviceManager,
        container_manager: ContainerManager,
        experiment_manager: ExperimentManager,
        task_manager: TaskManager,
    ):
        self._configuration_manager = configuration_manager
        self._device_manager = device_manager
        self._container_manager = container_manager
        self._experiment_manager = experiment_manager
        self._task_manager = task_manager
        self._loading_lock = AsyncRLock()

    async def load_labs(self, db: AsyncDbSession, labs: set[str]) -> None:
        """Load one or more labs into the orchestrator."""
        async with self._loading_lock:
            try:
                self._configuration_manager.load_labs(labs)
                await self._device_manager.update_devices(db, loaded_labs=labs)
                await self._container_manager.update_containers(db, loaded_labs=labs)
            except Exception:
                log.error(f"Error loading labs {labs}: {traceback.format_exc()}")
                raise

    async def unload_labs(self, db: AsyncDbSession, labs: set[str]) -> None:
        """Unload one or more labs from the orchestrator."""
        try:
            for lab_id in labs:
                await self._check_lab_usage(db, lab_id)

            async with self._loading_lock:
                self._configuration_manager.unload_labs(labs)
                await self._device_manager.update_devices(db, unloaded_labs=labs)
                await self._container_manager.update_containers(db, unloaded_labs=labs)
        except Exception:
            log.error(f"Error unloading labs {labs}: {traceback.format_exc()}")
            raise

    async def reload_labs(self, db: AsyncDbSession, lab_types: set[str]) -> None:
        """Reload one or more labs in the orchestrator with updated device plugin code."""
        for lab_type in lab_types:
            lab_config = self._configuration_manager.package_manager.read_lab_config(lab_type)
            device_types = {cfg.type for cfg in lab_config.devices.values()}
            for device_type in device_types:
                try:
                    self._configuration_manager.devices.reload_plugin(device_type)
                except Exception as e:
                    log.error(f"Failed to reload device '{device_type}' before lab reload: {e}")
                    raise

        async with self._loading_lock:
            # Determine which experiments will need re-loading after lab reload
            experiments_to_reload = self._get_experiments_for_labs(lab_types)

            # Ensure labs are not currently in use
            for lab_type in lab_types:
                await self._check_lab_usage(db, lab_type)

            try:
                # Unload: update in-memory config, devices, and containers
                self._configuration_manager.unload_labs(lab_types)
                await self._device_manager.update_devices(db, unloaded_labs=lab_types)
                await self._container_manager.update_containers(db, unloaded_labs=lab_types)

                # Load: update in-memory config, devices, and containers
                self._configuration_manager.load_labs(lab_types)
                await self._device_manager.update_devices(db, loaded_labs=lab_types)
                await self._container_manager.update_containers(db, loaded_labs=lab_types)

                # Finally, reload any dependent experiments
                await self.load_experiments(experiments_to_reload)
            except Exception as e:
                log.error(f"Error reloading labs {lab_types}: {e}")
                raise

    async def reload_devices(self, db: AsyncDbSession, lab_id: str, device_ids: list[str]) -> None:
        """Reload specific devices within a lab."""
        try:
            async with self._loading_lock:
                # Verify lab is loaded
                if lab_id not in self._configuration_manager.labs:
                    log.error(f"Cannot reload devices in lab '{lab_id}' as the lab is not loaded.")
                    raise EosConfigurationError(f"Lab '{lab_id}' is not loaded")

                # Check if any experiments or tasks are using the devices
                await self._check_device_usage(db, lab_id, device_ids)

                await self._device_manager.reload_devices(db, lab_id, device_ids)
        except Exception:
            log.error(f"Error reloading devices in lab '{lab_id}': {traceback.format_exc()}")
            raise

    def _get_experiments_for_labs(self, lab_types: set[str]) -> set[str]:
        """Get experiments that depend on the specified labs."""
        experiments_to_reload = set()
        for experiment_type, experiment_config in self._configuration_manager.experiments.items():
            if any(lab_type in experiment_config.labs for lab_type in lab_types):
                experiments_to_reload.add(experiment_type)
        return experiments_to_reload

    async def list_labs(self) -> dict[str, bool]:
        """Return a dictionary of lab types and a boolean indicating whether they are loaded."""
        return self._configuration_manager.get_loaded_labs()

    async def load_experiments(self, experiment_types: set[str]) -> None:
        """Load one or more experiments into the orchestrator."""
        if not experiment_types:
            return

        try:
            self._configuration_manager.load_experiments(experiment_types)
        except Exception:
            log.error(f"Error loading experiments: {traceback.format_exc()}")
            raise

    async def unload_experiments(self, db: AsyncDbSession, experiment_types: set[str]) -> None:
        """Unload one or more experiments from the orchestrator."""
        try:
            for experiment_type in experiment_types:
                await self._check_experiment_usage(db, experiment_type)

            self._configuration_manager.unload_experiments(experiment_types)
        except Exception:
            log.error(f"Error unloading experiments: {traceback.format_exc()}")
            raise

    async def reload_experiments(self, db: AsyncDbSession, experiment_types: set[str]) -> None:
        """Reload one or more experiments in the orchestrator."""
        async with self._loading_lock:
            try:
                for experiment_type in experiment_types:
                    await self._check_experiment_usage(db, experiment_type)

                self._configuration_manager.unload_experiments(experiment_types)
                self._configuration_manager.load_experiments(experiment_types)
            except Exception:
                log.error(f"Error reloading experiments: {traceback.format_exc()}")
                raise

    async def list_experiments(self) -> dict[str, bool]:
        """Return a dictionary of experiment types and a boolean indicating whether they are loaded."""
        return self._configuration_manager.get_loaded_experiments()

    async def reload_task_plugins(self, db: AsyncDbSession, task_types: set[str]) -> None:
        """Reload one or more task plugins in the orchestrator."""
        async with self._loading_lock:
            try:
                for task_type in task_types:
                    await self._check_task_usage(db, task_type)

                for task_type in task_types:
                    self._configuration_manager.tasks.reload_plugin(task_type)
                    log.info(f"Reloaded task '{task_type}'")
            except Exception:
                log.error(f"Error reloading tasks: {traceback.format_exc()}")
                raise

    async def _check_tasks_using_devices(
        self, db: AsyncDbSession, lab_id: str, device_ids: list[str] | None = None
    ) -> list[Task]:
        """
        Check if any standalone tasks are using specific devices in a lab.

        Includes both RUNNING and CREATED tasks.

        :param db: Database session
        :param lab_id: The lab ID containing the devices
        :param device_ids: Optional list of device IDs to check. If None, checks for any device in the lab.
        :return: List of active standalone tasks using the devices
        """
        # Get all active standalone tasks (both RUNNING and CREATED)
        active_tasks = []
        for status in [TaskStatus.RUNNING.value, TaskStatus.CREATED.value]:
            tasks = await self._task_manager.get_tasks(db, status=status)
            active_tasks.extend(tasks)

        # Filter tasks that use the specified devices
        device_tasks = []
        for task in active_tasks:
            if task.experiment_id and task.experiment_id != "on_demand":
                continue

            for device_config in task.devices:
                if device_config.lab == lab_id and (device_ids is None or device_config.id in device_ids):
                    device_tasks.append(task)
                    break

        return device_tasks

    async def _check_experiments_using_lab(self, db: AsyncDbSession, lab_id: str) -> list:
        """
        Check if any running experiments are using a lab.

        :param db: Database session
        :param lab_id: The lab ID to check
        :return: List of experiments using the lab
        """
        running_experiments = await self._experiment_manager.get_experiments(db, status=ExperimentStatus.RUNNING.value)
        return [
            experiment
            for experiment in running_experiments
            if lab_id in self._configuration_manager.experiments[experiment.type].labs
        ]

    async def _check_experiments_using_devices(self, db: AsyncDbSession, lab_id: str, device_ids: list[str]) -> list:
        """
        Check if any running experiments are using specific devices.

        :param db: Database session
        :param lab_id: The lab ID containing the devices
        :param device_ids: List of device IDs to check
        :return: List of experiments using the devices
        """
        running_experiments = await self._experiment_manager.get_experiments(db, status=ExperimentStatus.RUNNING.value)
        using_experiments = []

        for experiment in running_experiments:
            experiment_config = self._configuration_manager.experiments[experiment.type]
            if lab_id in experiment_config.labs:
                # Get the experiment's task graph to see if it uses any of these devices
                task_graph = experiment_config.task_graph
                for task in task_graph.tasks.values():
                    if task.lab == lab_id and any(device_id in task.devices for device_id in device_ids):
                        using_experiments.append(experiment)
                        break

        return using_experiments

    async def _check_experiment_usage(self, db: AsyncDbSession, experiment_type: str) -> None:
        """
        Check if an experiment type is currently in use (has running instances).

        :param db: Database session
        :param experiment_type: The experiment type to check
        :raises EosExperimentTypeInUseError: If the experiment has running instances
        """
        existing_experiments = await self._experiment_manager.get_experiments(
            db, status=ExperimentStatus.RUNNING.value, type=experiment_type
        )

        if existing_experiments:
            experiment_ids = ", ".join(experiment.id for experiment in existing_experiments)
            log.error(
                f"Cannot modify experiment type '{experiment_type}' as it has running instances: {experiment_ids}"
            )
            raise EosExperimentTypeInUseError(f"Experiment type '{experiment_type}' has running instances")

    async def _check_lab_usage(self, db: AsyncDbSession, lab_id: str) -> None:
        """
        Check if a lab is in use by any experiments or standalone tasks.

        :param db: Database session
        :param lab_id: The lab ID to check
        """
        # Check experiments using the lab
        using_experiments = await self._check_experiments_using_lab(db, lab_id)
        if using_experiments:
            experiment_ids = ", ".join(experiment.id for experiment in using_experiments)
            log.error(f"Cannot modify lab '{lab_id}' as it is in use by experiments: {experiment_ids}")
            raise EosExperimentTypeInUseError(f"Lab '{lab_id}' is in use by experiments")

        # Check standalone tasks using the lab
        standalone_tasks = await self._check_tasks_using_devices(db, lab_id)
        if standalone_tasks:
            task_ids = ", ".join(task.id for task in standalone_tasks)
            log.error(f"Cannot modify lab '{lab_id}' as it is in use by tasks: {task_ids}")
            raise EosExperimentTypeInUseError(f"Lab '{lab_id}' is in use by tasks")

    async def _check_device_usage(self, db: AsyncDbSession, lab_id: str, device_ids: list[str]) -> None:
        """
        Check if specific devices are in use by any experiments or standalone tasks.

        :param db: Database session
        :param lab_id: The lab ID containing the devices
        :param device_ids: List of device IDs to check
        """
        # Check experiments using the devices
        using_experiments = await self._check_experiments_using_devices(db, lab_id, device_ids)
        if using_experiments:
            experiment_ids = ", ".join(experiment.id for experiment in using_experiments)
            log.error(f"Cannot modify device(s) in lab '{lab_id}' as they are in use by experiments: {experiment_ids}")
            raise EosExperimentTypeInUseError(f"Devices in lab '{lab_id}' are in use by experiments")

        # Check standalone tasks using the devices
        standalone_tasks = await self._check_tasks_using_devices(db, lab_id, device_ids)
        if standalone_tasks:
            task_ids = ", ".join(task.id for task in standalone_tasks)
            log.error(f"Cannot modify device(s) in lab '{lab_id}' as they are in use by tasks: {task_ids}")
            raise EosExperimentTypeInUseError(f"Devices in lab '{lab_id}' are in use by tasks")

    async def _check_task_usage(self, db: AsyncDbSession, task_type: str) -> None:
        """
        Check if a task type is currently in use (has running or created instances).

        :param db: Database session
        :param task_type: The task type to check
        :raises EosExperimentTypeInUseError: If the task has active instances
        """
        active_tasks = []
        for status in [TaskStatus.RUNNING.value, TaskStatus.CREATED.value]:
            tasks = await self._task_manager.get_tasks(db, status=status, type=task_type)
            active_tasks.extend(tasks)

        if active_tasks:
            task_ids = ", ".join(task.id for task in active_tasks)
            log.error(f"Cannot modify task type '{task_type}' as it has active instances: {task_ids}")
            raise EosExperimentTypeInUseError(f"Task type '{task_type}' has active instances")
