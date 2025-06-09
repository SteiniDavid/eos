from eos.tasks.base_task import BaseTask


class BatchUpdateCounter(BaseTask):
    async def _execute(
        self,
        devices: BaseTask.DevicesType,
        parameters: BaseTask.ParametersType,
        containers: BaseTask.ContainersType,
    ) -> BaseTask.OutputType:
        counter = devices.get_all_by_type("stateful_counter")[0]
        new_value = counter.apply_operations(parameters["operations"])
        return {"value": new_value}, None, None
