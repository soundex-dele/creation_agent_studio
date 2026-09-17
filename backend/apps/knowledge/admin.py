from django.contrib import admin

from .models import KnowledgeBase, KnowledgeChunk, KnowledgeDocument


for model in (KnowledgeBase, KnowledgeDocument, KnowledgeChunk):
    admin.site.register(model)
