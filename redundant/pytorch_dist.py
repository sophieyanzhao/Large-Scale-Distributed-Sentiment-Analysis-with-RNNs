"""
Adapted from PyTorch 1.0 Distributed Trainer with Amazon AWS
"""


import time
import sys
import torch
import argparse
import torch.nn as nn
import torch.nn.parallel
import torch.distributed as dist
import torch.optim
import torch.utils.data
import torch.utils.data.distributed
import torchvision.transforms as transforms
import torchvision.datasets as datasets
import torchvision.models as models

from torch.multiprocessing import Pool, Process



class AverageMeter(object):
    """Computes and stores the average and current value"""
    def __init__(self):
        self.reset()

    def reset(self):
        self.val = 0
        self.avg = 0
        self.sum = 0
        self.count = 0

    def update(self, val, n=1):
        self.val = val
        self.sum += val * n
        self.count += n
        self.avg = self.sum / self.count

def accuracy(output, target, topk=(1,)):
    """Computes the precision@k for the specified values of k"""
    with torch.no_grad():
        maxk = max(topk)
        batch_size = target.size(0)

        _, pred = output.topk(maxk, 1, True, True)
        pred = pred.t()
        correct = pred.eq(target.view(1, -1).expand_as(pred))

        res = []
        for k in topk:
            correct_k = correct[:k].view(-1).float().sum(0, keepdim=True)
            res.append(correct_k.mul_(100.0 / batch_size))
        return res




def train(train_loader, model, criterion, optimizer, epoch):

    batch_time = AverageMeter()
    data_time = AverageMeter()
    losses = AverageMeter()
    top1 = AverageMeter()
    top5 = AverageMeter()

    # switch to train mode
    model.train()

    end = time.time()
    for i, (input, target) in enumerate(train_loader):

        # measure data loading time
        data_time.update(time.time() - end)

        # Create non_blocking tensors for distributed training
        input = input.cuda(non_blocking=True)
        target = target.cuda(non_blocking=True)

        # compute output
        output = model(input)
        loss = criterion(output, target)

        # measure accuracy and record loss
        prec1, prec5 = accuracy(output, target, topk=(1, 5))
        losses.update(loss.item(), input.size(0))
        top1.update(prec1[0], input.size(0))
        top5.update(prec5[0], input.size(0))

        # compute gradients in a backward pass
        optimizer.zero_grad()
        loss.backward()

        # Call step of optimizer to update model params
        optimizer.step()

        # measure elapsed time
        batch_time.update(time.time() - end)
        end = time.time()

        if i % 10 == 0:
            print('Epoch: [{0}][{1}/{2}]\t'
                  'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                  'Data {data_time.val:.3f} ({data_time.avg:.3f})\t'
                  'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                  'Prec@1 {top1.val:.3f} ({top1.avg:.3f})\t'
                  'Prec@5 {top5.val:.3f} ({top5.avg:.3f})'.format(
                   epoch, i, len(train_loader), batch_time=batch_time,
                   data_time=data_time, loss=losses, top1=top1, top5=top5))

def adjust_learning_rate(initial_lr, optimizer, epoch):
    """Sets the learning rate to the initial LR decayed by 10 every 30 epochs"""
    lr = initial_lr * (0.1 ** (epoch // 30))
    for param_group in optimizer.param_groups:
        param_group['lr'] = lr



def validate(val_loader, model, criterion):

    batch_time = AverageMeter()
    losses = AverageMeter()
    top1 = AverageMeter()
    top5 = AverageMeter()

    # switch to evaluate mode
    model.eval()

    with torch.no_grad():
        end = time.time()
        for i, (input, target) in enumerate(val_loader):

            input = input.cuda(non_blocking=True)
            target = target.cuda(non_blocking=True)

            # compute output
            output = model(input)
            loss = criterion(output, target)

            # measure accuracy and record loss
            prec1, prec5 = accuracy(output, target, topk=(1, 5))
            losses.update(loss.item(), input.size(0))
            top1.update(prec1[0], input.size(0))
            top5.update(prec5[0], input.size(0))

            # measure elapsed time
            batch_time.update(time.time() - end)
            end = time.time()

            if i % 100 == 0:
                print('Test: [{0}/{1}]\t'
                      'Time {batch_time.val:.3f} ({batch_time.avg:.3f})\t'
                      'Loss {loss.val:.4f} ({loss.avg:.4f})\t'
                      'Prec@1 {top1.val:.3f} ({top1.avg:.3f})\t'
                      'Prec@5 {top5.val:.3f} ({top5.avg:.3f})'.format(
                       i, len(val_loader), batch_time=batch_time, loss=losses,
                       top1=top1, top5=top5))

        print(' * Prec@1 {top1.avg:.3f} Prec@5 {top5.avg:.3f}'
              .format(top1=top1, top5=top5))

    return top1.avg

if __name__ == '__main__':
    
    initial_time = time.time()
    print("Collect Inputs...")

    parser = argparse.ArgumentParser()
    parser.add_argument("--local_rank", type=int)
    parser.add_argument("--dir", type=str, default='./data')
    args = parser.parse_args()
    
    print("Data Directory: {}".format(args.dir))

    # Batch Size for training and testing
    batch_size = 32
    
    # Number of additional worker processes for dataloading
    workers = 2

    # Number of epochs to train for
    num_epochs = 1

    # Starting Learning Rate
    starting_lr = 0.1

    # Distributed backend type
    dist_backend = 'nccl'

    print("Initialize Process Group...")
    # Initialize Process Group
    # v1 - init with url
    # dist.init_process_group(backend=dist_backend, init_method=dist_url, rank=int(sys.argv[1]), world_size=world_size)
    # v2 - init with file
    # dist.init_process_group(backend="nccl", init_method="file:///home/ubuntu/pt-distributed-tutorial/trainfile", rank=int(sys.argv[1]), world_size=world_size)
    # v3 - init with environment variables
    # dist.init_process_group(backend="nccl", init_method="env://", rank=int(sys.argv[1]), world_size=world_size)

    torch.cuda.set_device(args.local_rank)

    #torch.distributed.init_process_group(backend=dist_backend, init_method="file:///home/ubuntu/cloud/trainfile")
    torch.distributed.init_process_group(backend=dist_backend,
                                         init_method='env://')
    torch.multiprocessing.set_start_method('spawn')


    # Establish Local Rank and set device on this node
    local_rank = args.local_rank
    dp_device_ids = [local_rank]
    #torch.cuda.set_device(local_rank)



    print("Initialize Model...")
    # Construct Model
    model = models.resnet18(pretrained=False).cuda()
    # Make model DistributedDataParallel
    model = torch.nn.parallel.DistributedDataParallel(model, device_ids=dp_device_ids, output_device=local_rank)

    # define loss function (criterion) and optimizer
    criterion = nn.CrossEntropyLoss().cuda()
    optimizer = torch.optim.SGD(model.parameters(), starting_lr, momentum=0.9, weight_decay=1e-4)




    print("Initialize Dataloaders...")
    # Define the transform for the data. Notice, we must resize to 224x224 with this dataset and model.
    transform = transforms.Compose(
        [transforms.Resize(224),
         transforms.ToTensor(),
         transforms.Normalize((0.5, 0.5, 0.5), (0.5, 0.5, 0.5))])

    # Initialize Datasets. STL10 will automatically download if not present
    trainset = datasets.STL10(root=args.dir, split='train', download=True, transform=transform)
    valset = datasets.STL10(root=args.dir, split='test', download=True, transform=transform)

    # Create DistributedSampler to handle distributing the dataset across nodes when training
    # This can only be called after torch.distributed.init_process_group is called
    train_sampler = torch.utils.data.distributed.DistributedSampler(trainset)

    # Create the Dataloaders to feed data to the training and validation steps
    train_loader = torch.utils.data.DataLoader(trainset, batch_size=batch_size, shuffle=(train_sampler is None), num_workers=workers, pin_memory=False, sampler=train_sampler)
    val_loader = torch.utils.data.DataLoader(valset, batch_size=batch_size, shuffle=False, num_workers=workers, pin_memory=False)


    best_prec1 = 0

    for epoch in range(num_epochs):
        # Set epoch count for DistributedSampler
        train_sampler.set_epoch(epoch)

        # Adjust learning rate according to schedule
        adjust_learning_rate(starting_lr, optimizer, epoch)

        # train for one epoch
        print("\nBegin Training Epoch {}".format(epoch+1))
        train(train_loader, model, criterion, optimizer, epoch)

        # evaluate on validation set
        print("Begin Validation @ Epoch {}".format(epoch+1))
        prec1 = validate(val_loader, model, criterion)

        # remember best prec@1 and save checkpoint if desired
        # is_best = prec1 > best_prec1
        best_prec1 = max(prec1, best_prec1)

        print("Epoch Summary: ")
        print("\tEpoch Accuracy: {}".format(prec1))
        print("\tBest Accuracy: {}".format(best_prec1))
    print("total time: {}".format(time.time()-initial_time))