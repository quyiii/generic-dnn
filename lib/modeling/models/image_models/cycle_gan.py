import pdb
import torch
import itertools
import torch.nn as nn
from collections import OrderedDict
from .cycle_gan_nets import get_G, get_D
from lib.solver import get_loss_class, get_optim
from lib.util import ImagePool

'''
This model named cyle_gan, which is used to transform the image's style

Input: origin image 
Output: style-transformed image  

Generator G_A: fake_B = G_A(A)
Generator G_B: fake_A = G_B(B)

Discriminator D_A: D_A(B) vs D_A(fake_B)
Discriminator D_B: D_B(A) vs D_B(fake_A)

loss D_A: loss of Discriminator D_A
loss G_A: loss of Generator G_A ==> D_A 
loss cycle_A: lambda_A * ||G_B(G_A(A)) - A||
loss idt_A: lambda_identity * ||G_A(B) - B|| * lambda_B

loss D_B: loss of Discriminator D_B
loss G_B: loss of Generator G_B ==> D_B
loss cycle_B: lambda_B * ||G_A(G_B(B)) - B||
loss idt_B: lambda_identity * ||G_B(A) - A|| * lambda_A

'''

class CycleGan(nn.Module):
    def __init__(self, cfg):
        super(CycleGan, self).__init__()
        self.cfg = cfg
        self.device = torch.device("cuda:{}".format(cfg.MODEL.DEVICE_IDS[0])) if cfg.MODEL.DEVICE.lower() == 'cuda' else torch.device('cpu')
        self.direction = cfg.INPUT.DIRECTION
        self.is_train = cfg.TRAIN.IS_TRAIN
        self.input_channel = cfg.INPUT.CHANNEL if self.direction else cfg.OUTPUT.CHANNEL
        self.output_channel = cfg.OUTPUT.CHANNEL if self.direction else cfg.INPUT.CHANNEL

        self.loss_names = ['D_A', 'G_A', 'cycle_A', 'idt_A', 'D_B', 'G_B', 'cycle_B', 'idt_B']

        visual_names_A = ['real_A', 'fake_B', 'rec_A']
        visual_names_B = ['real_B', 'fake_A', 'rec_B']
        if self.cfg.TRAIN.IS_TRAIN and self.cfg.LOSS.LAMBDA_IDENTITY > 0.0:  # if identity loss is used, we also visualize idt_B=G_A(B) ad idt_A=G_A(B)
            visual_names_A.append('idt_B')
            visual_names_B.append('idt_A')

        self.visual_names = visual_names_A + visual_names_B 

        self.netG_A = get_G(self.input_channel, self.output_channel, 64, cfg.MODEL.CONSIST.G, cfg.MODEL.NORM,
                            cfg.MODEL.DROPOUT, cfg.MODEL.INIT, cfg.MODEL.INIT_GAIN)
        self.netG_B = get_G(self.output_channel, self.input_channel, 64, cfg.MODEL.CONSIST.G, cfg.MODEL.NORM,
                            cfg.MODEL.DROPOUT, cfg.MODEL.INIT, cfg.MODEL.INIT_GAIN)

        if not self.is_train:
            self.model_names = ['G_A', 'G_B']
        else:
            self.model_names = ['G_A', 'G_B', 'D_A', 'D_B'] 
            self.netD_A = get_D(self.output_channel, 64, cfg.MODEL.CONSIST.D, cfg.MODEL.NORM,
                                cfg.MODEL.INIT, cfg.MODEL.INIT_GAIN)
            self.netD_B = get_D(self.input_channel, 64, cfg.MODEL.CONSIST.D, cfg.MODEL.NORM,
                                cfg.MODEL.INIT, cfg.MODEL.INIT_GAIN)
            if cfg.LOSS.LAMBDA_IDENTITY > 0:
                assert(self.input_channel == self.output_channel)
            
            self.fake_A_pool = ImagePool(cfg.INPUT.POOL_SIZE)
            self.fake_B_pool = ImagePool(cfg.INPUT.POOL_SIZE)

            self.criterionGAN = get_loss_class(cfg, 0)('lsgan').to(self.device)
            self.criterionCycle = get_loss_class(cfg, 1)()
            self.criterionIdt = get_loss_class(cfg, 1)() 

            self.optimizer_G = get_optim(cfg, itertools.chain(self.netG_A.parameters(), self.netG_B.parameters()))
            self.optimizer_D = get_optim(cfg, itertools.chain(self.netD_A.parameters(), self.netD_B.parameters()))

    def set_input(self, data):
        self.real_A = data['A' if self.direction else 'B'].to(self.device)
        # print(self.real_A.shape)
        # pdb.set_trace()
        self.real_B = data['B' if self.direction else 'A'].to(self.device)
        self.iamge_paths = data['A_path' if self.direction else 'B_path']

    def forward(self):
        self.fake_B = self.netG_A(self.real_A)
        self.rec_A = self.netG_B(self.fake_B)
        self.fake_A = self.netG_B(self.real_B)
        self.rec_B = self.netG_A(self.fake_A)

    def backward_D_basic(self, netD, real, fake):
        """Calculate GAN loss for the discriminator

        Parameters:
            netD (network)      -- the discriminator D
            real (tensor array) -- real images
            fake (tensor array) -- images generated by a generator

        Return the discriminator loss.
        We also call loss_D.backward() to calculate the gradients.
        """
        # real
        pred_real = netD(real)
        loss_D_real = self.criterionGAN(pred_real, True)
        # fake
        pred_fake = netD(fake.detach())
        loss_D_fake = self.criterionGAN(pred_fake, False)
        # combine loss
        loss_D = (loss_D_real + loss_D_fake) * 0.5
        loss_D.backward()
        return loss_D.item()

    def backward_D_A(self):
        fake_B = self.fake_B_pool.query(self.fake_B)
        self.loss_D_A = self.backward_D_basic(self.netD_A, self.real_B, fake_B)

    def backward_D_B(self):
        fake_A = self.fake_A_pool.query(self.fake_A)
        self.loss_D_B = self.backward_D_basic(self.netD_B, self.real_B, fake_A)
    
    def backward_G(self):
        # weight for identity loss (A->A) (B->B)
        lambda_idt = self.cfg.LOSS.LAMBDA_IDENTITY
        # weight for cycle loss (A->B->A)
        lambda_A = self.cfg.LOSS.LAMBDA_A
        # weight for cycle loss (B->A->B)
        lambda_B = self.cfg.LOSS.LAMBDA_B

        if lambda_idt > 0:
            self.idt_A = self.netG_A(self.real_B)
            self.loss_idt_A = self.criterionIdt(self.idt_A, self.real_B) * lambda_B * lambda_idt
            self.idt_B = self.netG_B(self.real_A)
            self.loss_idt_B = self.criterionIdt(self.idt_B, self.real_A) * lambda_A * lambda_idt
        else:
            self.loss_idt_A = 0
            self.loss_idt_B = 0
        
        self.loss_G_A = self.criterionGAN(self.netD_A(self.fake_B), True)
        self.loss_G_B = self.criterionGAN(self.netD_B(self.fake_A), True)

        self.loss_cycle_A = self.criterionCycle(self.rec_A, self.real_A) * lambda_A
        self.loss_cycle_B = self.criterionCycle(self.rec_B, self.real_B) * lambda_B

        self.loss_G = self.loss_G_A + self.loss_G_B + self.loss_cycle_A + self.loss_cycle_B + self.loss_idt_A + self.loss_idt_B
        loss = self.loss_G.item()
        self.loss_G.backward()
        return loss

    def optimize_parameters(self):
        # train G
        self.forward()
        self.set_requires_grad([self.netD_A, self.netD_B], False)
        self.optimizer_G.zero_grad()
        loss = self.backward_G()
        self.optimizer_G.step()
        # train D
        self.set_requires_grad([self.netD_A, self.netD_B], True)
        self.optimizer_D.zero_grad()
        self.backward_D_A()
        self.backward_D_B()
        self.optimizer_D.step()
        return loss

    def get_current_visuals(self):
        """return current images"""
        visual_ret = OrderedDict()
        for name in  self.visual_names:
            if isinstance(name, str):
                visual_ret[name] = getattr(self, name)
        return visual_ret

    def eval(self):
        for name in self.model_names:
            if isinstance(name, str):
                net = getattr(self, 'net' + name)
                # net.eval() 不norm 不dropout
                net.eval()

    def test(self):
        self.eval()
        with torch.no_grad:
            self.forward()

    def set_requires_grad(self, nets, requires_grad=False):
        if not isinstance(nets, list):
            nets = [nets]
        for net in nets:
            if net is not None:
                for param in net.parameters():
                    param.requires_grad = requires_grad
