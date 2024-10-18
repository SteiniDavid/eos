class EosTaskError(Exception):
    pass


class EosTaskValidationError(EosTaskError):
    pass


class EosTaskInputResolutionError(EosTaskError):
    pass


class EosTaskStateError(EosTaskError):
    pass


class EosTaskExistsError(EosTaskError):
    pass


class EosTaskExecutionError(EosTaskError):
    pass


class EosTaskCancellationError(EosTaskError):
    pass


class EosTaskResourceAllocationError(EosTaskError):
    pass
