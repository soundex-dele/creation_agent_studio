import { api } from './api';
import { tenantApiRoot } from './tenantContext';
import type { AddressBook, Contact, ContactInput, ContactPage } from '@/types/contact';


function contactRoot(organizationId: string, applicationId: string) {
  return `${tenantApiRoot(organizationId)}/applications/${applicationId}`;
}

export function getAddressBook(organizationId: string, applicationId: string) {
  return api.get<AddressBook>(
    `${contactRoot(organizationId, applicationId)}/address-book`,
  );
}

export function listContacts(
  organizationId: string,
  applicationId: string,
  params: { q?: string; page?: number; page_size?: number; ordering?: string },
) {
  return api.get<ContactPage>(
    `${contactRoot(organizationId, applicationId)}/contacts`,
    params,
  );
}

export function createContact(
  organizationId: string,
  applicationId: string,
  input: ContactInput,
) {
  return api.post<Contact>(
    `${contactRoot(organizationId, applicationId)}/contacts`,
    input,
  );
}

export function updateContact(
  organizationId: string,
  applicationId: string,
  contact: Contact,
  input: ContactInput,
) {
  return api.patch<Contact>(
    `${contactRoot(organizationId, applicationId)}/contacts/${contact.id}`,
    { ...input, version: contact.version },
  );
}

export function deleteContact(
  organizationId: string,
  applicationId: string,
  contactId: string,
) {
  return api.delete<void>(
    `${contactRoot(organizationId, applicationId)}/contacts/${contactId}`,
  );
}
