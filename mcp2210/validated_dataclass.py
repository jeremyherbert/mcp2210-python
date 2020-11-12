from typing import Union


class ValidatedDataClass(object):
    def _validate(self):
        raise NotImplementedError

    def __post_init__(self):
        self._validate()

    def __setattr__(self, key, value):
        old_value = getattr(self, key)
        object.__setattr__(self, key, value)
        try:
            self._validate()
        except ValueError:
            # rollback
            object.__setattr__(self, key, old_value)
            raise


def check_in_closed_interval(variable: Union[int, float],
                             min: Union[int, float],
                             max: Union[int, float],
                             error_msg: str):
    if not min <= variable <= max:
        raise ValueError(error_msg)
