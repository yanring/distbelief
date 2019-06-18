# 
"""
Parameter server for distbelief
"""
import logging
import threading
import time
import torch
import torch.optim
from torch.multiprocessing import Process

from distbelief.utils import constant
from distbelief.utils.messaging import MessageCode, MessageListener, send_message, GSMessageCode, \
    GradientMessageListener
from distbelief.utils.serialization import ravel_model_params, ravel_sparse_gradient, unravel_sparse_gradient

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


# class GradientExecutor(Process):
#     """GradientExecutor"""
#
#     def __init__(self, share_tensor, shared_queue_recv, shared_queue_send, shared_list, rank=0, worker_num=None,
#                  global_model=None,
#                  synced_model=None, size_list=None, lr=0):
#         super().__init__()
#         _LOGGER.info("Creating GradientExecutor")
#         print("Creating GradientExecutor")
#         self.max_version = 0
#         self.worker_count = 0
#         self.worker_num = worker_num
#         self.global_model = global_model
#         self.synced_model = synced_model
#         self.synced_version = 0
#         self.acc_send_grad = synced_model.clone().zero_()
#         self.shared_tensor = share_tensor
#         self.shared_queue_recv = shared_queue_recv
#         self.shared_queue_send = shared_queue_send
#         self.shared_list = shared_list
#         self.net = None
#         self.rank = rank
#         self.lr = lr
#         self.sync_worker_model(1)
#         self.node_gradient = {}
#         self.size_list = size_list
#         self.agg_gradient = None
#         self.send_grad = self.acc_send_grad.clone()
#         self.cuda = self.acc_send_grad.is_cuda
#         print(constant.MODEL_SIZE)
#
#     def sync_worker_model(self, version):
#         self.send_message(self.synced_model, GSMessageCode.ModelUpdate, version, self.lr.value or 0.1)
#
#     def sync_model(self):
#         self.synced_model.copy_(self.global_model)
#         # print('sync_model : %f' % self.synced_model.sum())
#
#     def update(self, rank, version, gradient_update):
#         """
#         :param rank: rank of worker node
#         :param version: version of gradient
#         :param gradient_update: tensor, gradient update tensor
#         :return:
#         """
#         # print("update gradient from rank%d,version%d" % (rank, version))
#
#         self.global_model.add_(-1, gradient_update)
#
#         self.agg_gradient = self.global_model.add(-1, self.synced_model)
#
#         return self.agg_gradient, version
#
#     def receive(self, sender, message_code, gradient_version, lr, parameter):
#         # print("Processing message: {} from sender {} gradient version {}".format(message_code.name,
#         #                                                                          sender,
#         #                                                                          gradient_version))
#         self.max_version = max(self.max_version, gradient_version)
#         if sender == 1:
#             self.lr.value = lr
#             print(self.lr)
#         if message_code == GSMessageCode.GradientUpdate:
#             self.update(sender, gradient_version, parameter)
#             self.send_message(self.global_model, GSMessageCode.ModelUpdate,
#                               gradient_version=gradient_version)
#         elif message_code == GSMessageCode.SparseGradientUpdate:
#             start = time.time()
#             # parameter = unravel_sparse_gradient(parameter)
#             new_version = self.update(sender, gradient_version, parameter)
#             if sender == 1 and self.max_version % 150 is 1 and gradient_version > 20:
#                 self.sync_model()
#                 for i in range(1, self.worker_num):
#                     self.shared_list[i - 1] = 1
#             if self.shared_list[self.rank - 1]:
#                 self.acc_send_grad.zero_()
#                 self.sync_worker_model(gradient_version)
#                 self.shared_list[self.rank - 1] = 0
#             else:
#                 self.send_grad = self.agg_gradient.add(-1, self.acc_send_grad)
#                 # server_gradient_filter(self.size_list, self.send_grad, rate=0.01)
#                 # end = time.time()
#                 # print(abs(self.send_grad).sum())
#                 # print('server cal cost time : %f' % (end - start))
#                 self.send_message(ravel_sparse_gradient(self.send_grad), GSMessageCode.SparseGradientUpdate,
#                                   gradient_version, self.lr.value)
#                 self.acc_send_grad.add_(self.send_grad)
#             # else:
#             #     self.shared_tensor.copy_(self.agg_gradient.add(-1, self.acc_send_grad))
#             #     # server_gradient_filter(self.size_list, self.shared_tensor, rate=0.02)
#             #     end = time.time()
#             #     print('server cal cost time : %f' % (end - start))
#             #     self.send_message(torch.FloatTensor(range(1)), GSMessageCode.SparseGradientUpdate,
#             #                       gradient_version)
#             #     self.acc_send_grad.add_(self.shared_tensor)
#         else:
#             raise Exception('GSMessageCode not implemented')
#
#     def send_message(self, payload, message_code, gradient_version, lr):
#         self.shared_queue_send.put([payload.cpu(), message_code, gradient_version, lr])
#
#     def run(self):
#         while 1:
#             recv = self.shared_queue_recv.get()
#             # print('received', recv)
#             # print('end', time.time())
#             if self.max_version < 20:
#                 constant.MODEL_SIZE = self.global_model.numel()
#             self.receive(recv[0], recv[1], recv[2], recv[3], self.shared_tensor)
#             # print('Process %d is running' % self.rank)


un_synced_worker = set()

global_lr = 0.001


class GradientServer(GradientMessageListener):
    """GradientServer"""

    def __init__(self, model, rank=0, worker_num=None, global_model=None, synced_model=None, size_list=None):
        _LOGGER.info("Creating GradientServer")
        print("Creating GradientServer")
        # self.gradient_warehouse = gradient_warehouse
        # self.net = model
        self.max_version = 0
        self.worker_count = 0
        self.worker_num = worker_num
        self.global_model = global_model
        self.global_model.share_memory_()
        super(GradientServer, self).__init__(model_size=global_model.numel(), source=rank)
        self.synced_model = synced_model
        self.synced_model.share_memory_()
        self.synced_version = 0
        self.acc_send_grad = synced_model.clone().zero_()
        self.acc_send_grad.share_memory_()
        self.agg_gradient = None
        self.size_list = size_list
        self.send_grad = self.acc_send_grad.clone()
        self.cuda = self.synced_model.is_cuda
        if rank == 1:
            for i in range(1, self.worker_num):
                self.sync_worker_model(i, 1)
        self.node_gradient = {}

    def sync_worker_model(self, sender, version):
        send_message(GSMessageCode.ModelUpdate, self.synced_model, dst=sender, gradient_version=version, lr=global_lr)

    def sync_model(self):
        self.synced_model.copy_(self.global_model)
        # self.synced_version = self
        return self.synced_model

    def update(self, rank, version, gradient_update):
        """
        :param rank: rank of worker node
        :param version: version of gradient
        :param gradient_update: tensor, gradient update tensor
        :return:
        """
        # print("update gradient from rank%d,version%d" % (rank, version))
        self.global_model.add_(-1, gradient_update)

        self.agg_gradient = self.global_model.add(-1, self.synced_model)

        return self.agg_gradient, version

    def receive(self, sender, message_code, gradient_version, lr, parameter):
        global un_synced_worker, global_lr
        # print("rank {} Processing message: {} from sender {} gradient version {}".format(self.source, message_code.name,
        #                                                                                  sender,
        #                                                                                  gradient_version))
        self.max_version = max(self.max_version, gradient_version)
        if sender == 1:
            global_lr = lr

        if message_code == GSMessageCode.GradientUpdate:
            if self.cuda:
                self.update(sender, gradient_version, parameter.cuda().float())
            else:
                self.update(sender, gradient_version, parameter.float())

            send_message(GSMessageCode.ModelUpdate, self.global_model, dst=sender,
                         gradient_version=gradient_version)
        elif message_code == GSMessageCode.SparseGradientUpdate:
            if self.cuda:
                send_grad = self.update(sender, gradient_version, unravel_sparse_gradient(parameter).cuda())
            else:
                send_grad = self.update(sender, gradient_version, unravel_sparse_gradient(parameter))

            if sender == 1 and self.max_version % 150 is 1 and gradient_version > 20:
                self.sync_model()
                un_synced_worker = set(range(1, self.worker_num))
            if sender in un_synced_worker:
                self.acc_send_grad.zero_()
                self.sync_worker_model(sender, gradient_version)
                un_synced_worker.remove(sender)
            else:
                self.send_grad = self.agg_gradient.add(-1, self.acc_send_grad)
                # server_gradient_filter(self.size_list, self.send_grad, rate=0.1 * global_lr)
                # end = time.time()

                # print(abs(self.send_grad).sum())
                # print('server cal cost time : %f' % (end - start))
                send_message(GSMessageCode.SparseGradientUpdate, ravel_sparse_gradient(self.send_grad), sender,
                             gradient_version, lr=global_lr)

                self.acc_send_grad.add_(self.send_grad)

        else:
            raise Exception('GSMessageCode not implemented')
