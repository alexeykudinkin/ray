from typing import Any, Dict

import tree  # pip install dm_tree

from ray.rllib.algorithms.ppo.ppo_rl_module import PPORLModule
from ray.rllib.core.columns import Columns
from ray.rllib.core.models.base import ACTOR, CRITIC
from ray.rllib.core.models.tf.encoder import ENCODER_OUT
from ray.rllib.core.rl_module.apis.value_function_api import ValueFunctionAPI
from ray.rllib.core.rl_module.rl_module import RLModule
from ray.rllib.core.rl_module.tf.tf_rl_module import TfRLModule
from ray.rllib.utils.annotations import override
from ray.rllib.utils.framework import try_import_tf
from ray.rllib.utils.nested_dict import NestedDict
from ray.rllib.utils.typing import TensorType

tf1, tf, _ = try_import_tf()


class PPOTfRLModule(TfRLModule, PPORLModule):
    framework: str = "tf2"

    @override(RLModule)
    def _forward_inference(self, batch: NestedDict) -> Dict[str, Any]:
        output = {}

        # Encoder forward pass.
        encoder_outs = self.encoder(batch)
        if Columns.STATE_OUT in encoder_outs:
            output[Columns.STATE_OUT] = encoder_outs[Columns.STATE_OUT]

        # Pi head.
        output[Columns.ACTION_DIST_INPUTS] = self.pi(encoder_outs[ENCODER_OUT][ACTOR])

        return output

    @override(RLModule)
    def _forward_exploration(self, batch: NestedDict, **kwargs) -> Dict[str, Any]:
        """PPO forward pass during exploration.

        Besides the action distribution, this method also returns the parameters of
        the policy distribution to be used for computing KL divergence between the old
        policy and the new policy during training.
        """
        # TODO (sven): Make this the only bahevior once PPO has been migrated
        #  to new API stack (including EnvRunners!).
        if self.config.model_config_dict.get("uses_new_env_runners"):
            return self._forward_inference(batch=batch)

        output = {}

        # Shared encoder
        encoder_outs = self.encoder(batch)
        if Columns.STATE_OUT in encoder_outs:
            output[Columns.STATE_OUT] = encoder_outs[Columns.STATE_OUT]

        # Value head
        if not self.config.inference_only:
            # Only, if this is a learner module we have a value function head.
            vf_out = self.vf(encoder_outs[ENCODER_OUT][CRITIC])
            output[Columns.VF_PREDS] = tf.squeeze(vf_out, axis=-1)

        # Policy head
        action_logits = self.pi(encoder_outs[ENCODER_OUT][ACTOR])
        output[Columns.ACTION_DIST_INPUTS] = action_logits

        return output

    @override(TfRLModule)
    def _forward_train(self, batch: NestedDict):
        output = {}

        # Shared encoder.
        encoder_outs = self.encoder(batch)
        if Columns.STATE_OUT in encoder_outs:
            output[Columns.STATE_OUT] = encoder_outs[Columns.STATE_OUT]

        # Value head.
        vf_out = self.vf(encoder_outs[ENCODER_OUT][CRITIC])
        # Squeeze out last dim (value function node).
        output[Columns.VF_PREDS] = tf.squeeze(vf_out, axis=-1)

        # Policy head.
        action_logits = self.pi(encoder_outs[ENCODER_OUT][ACTOR])
        output[Columns.ACTION_DIST_INPUTS] = action_logits

        return output

    @override(ValueFunctionAPI)
    def compute_values(self, batch: Dict[str, Any]) -> TensorType:
        infos = batch.pop(Columns.INFOS, None)
        batch = tree.map_structure(lambda s: tf.convert_to_tensor(s), batch)
        if infos is not None:
            batch[Columns.INFOS] = infos

        # Separate vf-encoder.
        if hasattr(self.encoder, "critic_encoder"):
            encoder_outs = self.encoder.critic_encoder(batch)[ENCODER_OUT]
        # Shared encoder.
        else:
            encoder_outs = self.encoder(batch)[ENCODER_OUT][CRITIC]
        # Value head.
        vf_out = self.vf(encoder_outs)
        # Squeeze out last dimension (single node value head).
        return tf.squeeze(vf_out, -1)
