from eos.tasks.base_task import BaseTask


class SetCounter(BaseTask):
    async def _execute(
        self,
        devices: BaseTask.DevicesType,
        parameters: BaseTask.ParametersType,
        containers: BaseTask.ContainersType,
    ) -> BaseTask.OutputType:
        counter = devices.get_all_by_type("stateful_counter")[0]
        counter.set_state(parameters["value"])
        return {"value": counter.get_state()["value"]}, None, None
