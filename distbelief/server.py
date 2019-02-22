# 
"""
Parameter server for distbelief
"""

import logging
import threading
import torch
import torch.optim

from distbelief.utils.messaging import MessageCode, MessageListener, send_message, GSMessageCode, \
    GradientMessageListener
from distbelief.utils.serialization import ravel_model_params, unravel_sparse_gradient, ravel_sparse_gradient, \
    server_gradient_filter

_LOGGER = logging.getLogger(__name__)
cond = threading.Condition()


class ParameterServer(MessageListener):
    """ParameterServer"""

    def __init__(self, model):
        _LOGGER.info("Creating ParameterServer")
        print("Creating ParameterServer")
        self.parameter_shard = torch.rand(ravel_model_params(model).numel())
        self.model = model
        # init superclass
        super(ParameterServer, self).__init__(model)

    def receive(self, sender, message_code, parameter):
        print("Processing message: {} from sender {}".format(message_code.name, sender))

        if message_code == MessageCode.ParameterUpdate:
            # be sure to clone here
            self.parameter_shard = parameter.clone()

        elif message_code == MessageCode.ParameterRequest:
            send_message(MessageCode.ParameterUpdate, self.parameter_shard, dst=sender)

        elif message_code == MessageCode.GradientUpdate:
            self.parameter_shard.add_(parameter)


class GradientWarehouse:
    """Warehouse for gradient, store multiple version of gradient"""

    def __init__(self, version_num=10, worker_num=3, model=None):
        self.gradient_storage = {}
        self.gradient_storage_state = {}
        self.max_version = 0
        self.worker_count = 0
        self.worker_num = worker_num
        self.global_model = ravel_model_params(model, cuda=True)
        self.synced_model = ravel_model_params(model, cuda=True)
        self.synced_version = 0
        self.un_synced_worker = {}

    def update(self, rank, version, gradient_update):
        """
        :param rank: rank of worker node
        :param version: version of gradient
        :param gradient_update: tensor, gradient update tensor
        :return:
        """
        print("update gradient from rank%d,version%d" % (rank, version))

        self.global_model.add_(-1, gradient_update)

        agg_gradient = self.global_model.add(-1, self.synced_model)

        self.max_version = max(self.max_version, version)

        return agg_gradient, version

    def sync_model(self):
        self.synced_model.copy_(self.global_model)
        # self.synced_version = self
        return self.synced_model


class GradientServer(GradientMessageListener):
    """GradientServer"""

    def __init__(self, model, gradient_warehouse, storage_num=10, rank=0):
        _LOGGER.info("Creating GradientServer")
        print("Creating GradientServer")
        self.gradient_warehouse = gradient_warehouse
        super(GradientServer, self).__init__(model, source=rank)
        self.net = model
        self.acc_send_grad = torch.zeros(ravel_model_params(model).numel()).cuda()
        if rank == 1:
            for i in range(1, self.gradient_warehouse.worker_num):
                self.sync_worker_model(i, 1)
        self.node_gradient = {}

    def sync_worker_model(self, sender, version):
        # if sender == 2:
        model = self.gradient_warehouse.synced_model
        send_message(GSMessageCode.ModelUpdate, model, dst=sender, gradient_version=version)

    def receive(self, sender, message_code, gradient_version, parameter):
        print("rank {} Processing message: {} from sender {} gradient version {}".format(self.source, message_code.name,
                                                                                         sender,
                                                                                         gradient_version))

        if message_code == GSMessageCode.GradientUpdate:
            self.gradient_warehouse.update(sender, gradient_version, parameter)
            send_message(GSMessageCode.ModelUpdate, self.gradient_warehouse.global_model, dst=sender,
                         gradient_version=gradient_version)
        elif message_code == GSMessageCode.SparseGradientUpdate:
            parameter = unravel_sparse_gradient(parameter)
            agg_gradient, new_version = self.gradient_warehouse.update(sender, gradient_version, parameter)
            if sender == 1 and self.gradient_warehouse.max_version % 100 is 1 and gradient_version > 20:
                self.gradient_warehouse.sync_model()
                self.gradient_warehouse.un_synced_worker = set(range(1, self.gradient_warehouse.worker_num))
            if sender in self.gradient_warehouse.un_synced_worker:
                self.acc_send_grad.zero_()
                self.sync_worker_model(sender, new_version)
                self.gradient_warehouse.un_synced_worker.remove(sender)
            else:
                send_grad = agg_gradient.add(-1, self.acc_send_grad)
                server_gradient_filter(self.net, send_grad, rate=0.02)
                self.acc_send_grad.add_(send_grad)
                send_grad = ravel_sparse_gradient(send_grad)
                send_message(GSMessageCode.SparseGradientUpdate, send_grad,
                             dst=sender,
                             gradient_version=new_version)

        else:
            raise Exception('GSMessageCode not implemented')
