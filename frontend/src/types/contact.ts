export type ContactMethodKind = 'phone' | 'email' | 'wechat' | 'other';

export interface ContactMethod {
  id?: string;
  kind: ContactMethodKind;
  label: string;
  value: string;
  is_primary: boolean;
}

export interface Contact {
  id: string;
  name: string;
  company: string;
  department: string;
  job_title: string;
  notes: string;
  avatar: string;
  version: number;
  methods: ContactMethod[];
  created_at: string;
  updated_at: string;
}

export interface ContactInput {
  name: string;
  company?: string;
  department?: string;
  job_title?: string;
  notes?: string;
  avatar?: string;
  methods?: ContactMethod[];
}

export interface AddressBook {
  id: string;
  application_id: number;
  name: string;
  contact_count: number;
  created_at: string;
  updated_at: string;
}

export interface ContactPage {
  count: number;
  next: string | null;
  previous: string | null;
  results: Contact[];
}
