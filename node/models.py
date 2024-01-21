from django.db import models

# Create your models here.

class Block(models.Model):
    hash = models.CharField(max_length=64, unique= True)
    content = models.TextField()
    address = models.CharField(max_length = 128)
    random = models.BigIntegerField()
    difficulty = models.DecimalField(max_digits=3, decimal_places=1)
    reward = models.DecimalField(max_digits=14, decimal_places=6)
    timestamp = models.DateTimeField()

    def __str__(self):
        return self.hash
    class Meta:
        db_table = 'blocks'


class Transaction(models.Model):
    block_hash = models.ForeignKey(Block, on_delete=models.CASCADE)
    tx_hash = models.CharField(max_length=64, unique= True)
    tx_hex = models.TextField()
    inputs_addresses = models.TextField()
    outputs_addresses = models.TextField()
    outputs_amounts = models.BigIntegerField()
    fees = models.DecimalField(max_digits=14, decimal_places=6)

    class Meta:
        db_table = 'transactions'

class UnspentOutput(models.Model):
    tx_hash = models.ForeignKey(Transaction, on_delete=models.CASCADE)
    index = models.IntegerField()
    address = models.TextField()
    class Meta:
        db_table = 'unspent_outputs'


class PendingTransactions(models.Model):
    tx_hash = models.CharField(max_length=64, unique= True)
    tx_hex = models.TextField()
    inputs_addresses = models.TextField()
    fees = models.DecimalField(max_digits=14, decimal_places=6)
    propagation_time = models.DateTimeField(auto_now_add=True)
    class Meta:
        db_table = 'pending_transactions'

class PendingSpentOutputs(models.Model):
    tx_hash = models.ForeignKey(Transaction, on_delete=models.CASCADE)
    index = models.IntegerField()
    address = models.TextField()
    class Meta:
        db_table = 'pending_spent_outputs'
