import warnings

from nengo.config import SupportDefaultsMixin
from nengo.exceptions import ValidationError
from nengo.params import (
    Default,
    IntParam,
    FrozenObject,
    NumberParam,
    Parameter,
)
from nengo.synapses import Lowpass, SynapseParam
from nengo.utils.numpy import is_iterable


class LearningRuleTypeSizeInParam(IntParam):
    valid_strings = ("pre", "post", "mid", "pre_state", "post_state")

    def coerce(self, instance, size_in):
        if isinstance(size_in, str):
            if size_in not in self.valid_strings:
                raise ValidationError(
                    "%r is not a valid string value (must be one of %s)"
                    % (size_in, self.strings),
                    attr=self.name,
                    obj=instance,
                )
            return size_in
        else:
            return super().coerce(instance, size_in)  # IntParam validation


class LearningRuleType(FrozenObject, SupportDefaultsMixin):
    """Base class for all learning rule objects.

    To use a learning rule, pass it as a ``learning_rule_type`` keyword
    argument to the `~nengo.Connection` on which you want to do learning.

    Each learning rule exposes two important pieces of metadata that the
    builder uses to determine what information should be stored.

    The ``size_in`` is the dimensionality of the incoming error signal. It
    can either take an integer or one of the following string values:

    * ``'pre'``: vector error signal in pre-object space
    * ``'post'``: vector error signal in post-object space
    * ``'mid'``: vector error signal in the ``conn.size_mid`` space
    * ``'pre_state'``: vector error signal in pre-synaptic ensemble space
    * ``'post_state'``: vector error signal in post-synaptic ensemble space

    The difference between ``'post_state'`` and ``'post'`` is that with the
    former, if a ``Neurons`` object is passed, it will use the dimensionality
    of the corresponding ``Ensemble``, whereas the latter simply uses the
    ``post`` object ``size_in``. Similarly with ``'pre_state'`` and ``'pre'``.

    The ``modifies`` attribute denotes the signal targeted by the rule.
    Options are:

    * ``'encoders'``
    * ``'decoders'``
    * ``'weights'``

    Parameters
    ----------
    learning_rate : float, optional
        A scalar indicating the rate at which ``modifies`` will be adjusted.
    size_in : int, str, optional
        Dimensionality of the error signal (see above).

    Attributes
    ----------
    learning_rate : float
        A scalar indicating the rate at which ``modifies`` will be adjusted.
    size_in : int, str
        Dimensionality of the error signal.
    modifies : str
        The signal targeted by the learning rule.
    """

    modifies = None
    probeable = ()

    learning_rate = NumberParam("learning_rate", low=0, readonly=True, default=1e-6)
    size_in = LearningRuleTypeSizeInParam("size_in", low=0)

    def __init__(self, learning_rate=Default, size_in=0):
        super().__init__()
        self.learning_rate = learning_rate
        self.size_in = size_in


class PES(LearningRuleType):
    """Prescribed Error Sensitivity learning rule.

    Modifies a connection's decoders to minimize an error signal provided
    through a connection to the connection's learning rule.

    Parameters
    ----------
    learning_rate : float, optional
        A scalar indicating the rate at which weights will be adjusted.
    pre_synapse : `.Synapse`, optional
        Synapse model used to filter the pre-synaptic activities.

    Attributes
    ----------
    learning_rate : float
        A scalar indicating the rate at which weights will be adjusted.
    pre_synapse : `.Synapse`
        Synapse model used to filter the pre-synaptic activities.
    """

    modifies = "decoders"
    probeable = ("error", "activities", "delta")

    learning_rate = NumberParam("learning_rate", low=0, readonly=True, default=1e-4)
    pre_synapse = SynapseParam("pre_synapse", default=Lowpass(tau=0.005), readonly=True)

    def __init__(self, learning_rate=Default, pre_synapse=Default):
        super().__init__(learning_rate, size_in="post_state")
        if learning_rate is not Default and learning_rate >= 1.0:
            warnings.warn(
                "This learning rate is very high, and can result "
                "in floating point errors from too much current."
            )

        self.pre_synapse = pre_synapse


def _remove_default_post_synapse(argreprs, default):
    default_post_synapse = "post_synapse=%r" % (default,)
    if default_post_synapse in argreprs:
        argreprs.remove(default_post_synapse)
    return argreprs


class BCM(LearningRuleType):
    """Bienenstock-Cooper-Munroe learning rule.

    Modifies connection weights as a function of the presynaptic activity
    and the difference between the postsynaptic activity and the average
    postsynaptic activity.

    Notes
    -----
    The BCM rule is dependent on pre and post neural activities,
    not decoded values, and so is not affected by changes in the
    size of pre and post ensembles. However, if you are decoding from
    the post ensemble, the BCM rule will have an increased effect on
    larger post ensembles because more connection weights are changing.
    In these cases, it may be advantageous to scale the learning rate
    on the BCM rule by ``1 / post.n_neurons``.

    Parameters
    ----------
    learning_rate : float, optional
        A scalar indicating the rate at which weights will be adjusted.
    pre_synapse : `.Synapse`, optional
        Synapse model used to filter the pre-synaptic activities.
    post_synapse : `.Synapse`, optional
        Synapse model used to filter the post-synaptic activities.
        If None, ``post_synapse`` will be the same as ``pre_synapse``.
    theta_synapse : `.Synapse`, optional
        Synapse model used to filter the theta signal.

    Attributes
    ----------
    learning_rate : float
        A scalar indicating the rate at which weights will be adjusted.
    post_synapse : `.Synapse`
        Synapse model used to filter the post-synaptic activities.
    pre_synapse : `.Synapse`
        Synapse model used to filter the pre-synaptic activities.
    theta_synapse : `.Synapse`
        Synapse model used to filter the theta signal.
    """

    modifies = "weights"
    probeable = ("theta", "pre_filtered", "post_filtered", "delta")

    learning_rate = NumberParam("learning_rate", low=0, readonly=True, default=1e-9)
    pre_synapse = SynapseParam("pre_synapse", default=Lowpass(tau=0.005), readonly=True)
    post_synapse = SynapseParam("post_synapse", default=None, readonly=True)
    theta_synapse = SynapseParam(
        "theta_synapse", default=Lowpass(tau=1.0), readonly=True
    )

    def __init__(
        self,
        learning_rate=Default,
        pre_synapse=Default,
        post_synapse=Default,
        theta_synapse=Default,
    ):
        super().__init__(learning_rate, size_in=0)

        self.pre_synapse = pre_synapse
        self.post_synapse = (
            self.pre_synapse if post_synapse is Default else post_synapse
        )
        self.theta_synapse = theta_synapse

    @property
    def _argreprs(self):
        return _remove_default_post_synapse(super()._argreprs, self.pre_synapse)


class Oja(LearningRuleType):
    """Oja learning rule.

    Modifies connection weights according to the Hebbian Oja rule, which
    augments typically Hebbian coactivity with a "forgetting" term that is
    proportional to the weight of the connection and the square of the
    postsynaptic activity.

    Notes
    -----
    The Oja rule is dependent on pre and post neural activities,
    not decoded values, and so is not affected by changes in the
    size of pre and post ensembles. However, if you are decoding from
    the post ensemble, the Oja rule will have an increased effect on
    larger post ensembles because more connection weights are changing.
    In these cases, it may be advantageous to scale the learning rate
    on the Oja rule by ``1 / post.n_neurons``.

    Parameters
    ----------
    learning_rate : float, optional
        A scalar indicating the rate at which weights will be adjusted.
    pre_synapse : `.Synapse`, optional
        Synapse model used to filter the pre-synaptic activities.
    post_synapse : `.Synapse`, optional
        Synapse model used to filter the post-synaptic activities.
        If None, ``post_synapse`` will be the same as ``pre_synapse``.
    beta : float, optional
        A scalar weight on the forgetting term.

    Attributes
    ----------
    beta : float
        A scalar weight on the forgetting term.
    learning_rate : float
        A scalar indicating the rate at which weights will be adjusted.
    post_synapse : `.Synapse`
        Synapse model used to filter the post-synaptic activities.
    pre_synapse : `.Synapse`
        Synapse model used to filter the pre-synaptic activities.
    """

    modifies = "weights"
    probeable = ("pre_filtered", "post_filtered", "delta")

    learning_rate = NumberParam("learning_rate", low=0, readonly=True, default=1e-6)
    pre_synapse = SynapseParam("pre_synapse", default=Lowpass(tau=0.005), readonly=True)
    post_synapse = SynapseParam("post_synapse", default=None, readonly=True)
    beta = NumberParam("beta", low=0, readonly=True, default=1.0)

    def __init__(
        self,
        learning_rate=Default,
        pre_synapse=Default,
        post_synapse=Default,
        beta=Default,
    ):
        super().__init__(learning_rate, size_in=0)

        self.beta = beta
        self.pre_synapse = pre_synapse
        self.post_synapse = (
            self.pre_synapse if post_synapse is Default else post_synapse
        )

    @property
    def _argreprs(self):
        return _remove_default_post_synapse(super()._argreprs, self.pre_synapse)


class Voja(LearningRuleType):
    """Vector Oja learning rule.

    Modifies an ensemble's encoders to be selective to its inputs.

    A connection to the learning rule will provide a scalar weight for the
    learning rate, minus 1. For instance, 0 is normal learning, -1 is no
    learning, and less than -1 causes anti-learning or "forgetting".

    Parameters
    ----------
    post_tau : float, optional
        Filter constant on activities of neurons in post population.
    learning_rate : float, optional
        A scalar indicating the rate at which encoders will be adjusted.
    post_synapse : `.Synapse`, optional
        Synapse model used to filter the post-synaptic activities.

    Attributes
    ----------
    learning_rate : float
        A scalar indicating the rate at which encoders will be adjusted.
    post_synapse : `.Synapse`
        Synapse model used to filter the post-synaptic activities.
    """

    modifies = "encoders"
    probeable = ("post_filtered", "scaled_encoders", "delta")

    learning_rate = NumberParam("learning_rate", low=0, readonly=True, default=1e-2)
    post_synapse = SynapseParam(
        "post_synapse", default=Lowpass(tau=0.005), readonly=True
    )

    def __init__(self, learning_rate=Default, post_synapse=Default):
        super().__init__(learning_rate, size_in=1)

        self.post_synapse = post_synapse


class LearningRuleTypeParam(Parameter):
    def check_rule(self, instance, rule):
        if not isinstance(rule, LearningRuleType):
            raise ValidationError(
                "'%s' must be a learning rule type or a dict or "
                "list of such types." % rule,
                attr=self.name,
                obj=instance,
            )
        if rule.modifies not in ("encoders", "decoders", "weights"):
            raise ValidationError(
                "Unrecognized target %r" % rule.modifies, attr=self.name, obj=instance
            )

    def coerce(self, instance, rule):
        if is_iterable(rule):
            for r in rule.values() if isinstance(rule, dict) else rule:
                self.check_rule(instance, r)
        elif rule is not None:
            self.check_rule(instance, rule)
        return super().coerce(instance, rule)
