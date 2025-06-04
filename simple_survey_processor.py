#!/usr/bin/env python3
"""
Survey Data Processor - Windows Compatible Version with Text Field Support
Updated version with proper text field handling and SPSS variable naming
"""

import json
import pandas as pd
import numpy as np
import requests
from pathlib import Path
from typing import Dict, Any, List, Tuple
import sys
import os

# Try to import pyreadstat, but don't fail if it's not available
try:
    import pyreadstat
    SPSS_AVAILABLE = True
except ImportError:
    SPSS_AVAILABLE = False
    print("Note: SPSS export not available. CSV and Excel files will be created instead.")

def get_downloads_folder():
    """Get the Downloads folder path for Windows/Mac/Linux."""
    if sys.platform == 'win32':
        import winreg
        sub_key = r'SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders'
        downloads_guid = '{374DE290-123F-4565-9164-39C4925E467B}'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, sub_key) as key:
            downloads_path = winreg.QueryValueEx(key, downloads_guid)[0]
        return Path(downloads_path)
    else:
        return Path.home() / 'Downloads'

def download_survey_data(survey_id: str, token: str):
    """Download survey structure and responses from API."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    print(f"Downloading survey {survey_id}...")
    
    # Download survey structure
    survey_url = f"https://backend.workey.ai/surveys/{survey_id}"
    survey_response = requests.get(survey_url, headers=headers)
    survey_response.raise_for_status()
    survey_data = survey_response.json()
    
    # Download responses
    replies_url = f"https://backend.workey.ai/surveys/replies/{survey_id}"
    replies_response = requests.get(replies_url, headers=headers)
    replies_response.raise_for_status()
    replies_data = replies_response.json()
    
    print("Data downloaded successfully!")
    return survey_data, replies_data

def create_question_mapping(survey_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Create mappings for all question types from the survey structure."""
    questions = {}
    id_to_key = {}
    value_labels = {}
    choice_to_key = {}  # Mapping for choice IDs to question keys
    element_to_key = {}  # Mapping for element IDs to question keys (for text fields)
    measurement_types = {}  # Dict for measurement types
    
    for page in survey_data['pages']:
        for element in page['elements']:
            element_id = str(element['id'])
            
            # Handle different element types
            if element['@type'] == 'Matrix':
                # Handle Matrix questions
                col_labels = {
                    int(col['value']): col['text']['default']
                    for col in element['columns']
                    if col.get('value') is not None
                }
                
                for row in element['rows']:
                    if row.get('itemKey'):
                        questions[row['itemKey']] = {
                            'type': 'Matrix',
                            'text': row['text']['default'],
                            'id': row['id']
                        }
                        id_to_key[str(row['id'])] = row['itemKey']
                        measurement_types[row['itemKey']] = 'Nominal'
                        if col_labels:
                            value_labels[row['itemKey']] = col_labels
                            
            elif element['@type'] == 'Radiogroup':
                if element.get('itemKey'):
                    item_key = element['itemKey']
                    questions[item_key] = {
                        'type': 'Radiogroup',
                        'text': element['title']['default'],
                        'id': element['id']
                    }
                    id_to_key[str(element['id'])] = item_key
                    measurement_types[item_key] = 'Nominal'
                    
                    # Create value labels and choice mapping
                    radio_labels = {}
                    for choice in element['choices']:
                        if choice.get('value') is not None:
                            value = int(choice['value'])
                            radio_labels[value] = choice['text']['default']
                            choice_to_key[str(choice['id'])] = item_key
                    
                    if radio_labels:
                        value_labels[item_key] = radio_labels
                    
            elif element['@type'] == 'Number':
                if element.get('itemKey'):
                    questions[element['itemKey']] = {
                        'type': 'Number',
                        'text': element['title']['default'],
                        'id': element['id'],
                        'min': element.get('min'),
                        'max': element.get('max')
                    }
                    id_to_key[str(element['id'])] = element['itemKey']
                    element_to_key[element_id] = element['itemKey']
                    measurement_types[element['itemKey']] = 'Scale'
                    
            elif element['@type'] == 'Text':
                # Handle text fields - create a synthetic itemKey if none exists
                item_key = element.get('itemKey')
                if not item_key:
                    item_key = f"text_{element['id']}"
                
                questions[item_key] = {
                    'type': 'Text',
                    'text': element['title']['default'],
                    'id': element['id']
                }
                element_to_key[element_id] = item_key
                measurement_types[item_key] = 'Nominal'  # Text is always nominal
    
    return {
        'questions': questions,
        'id_to_key': id_to_key,
        'value_labels': value_labels,
        'choice_to_key': choice_to_key,
        'element_to_key': element_to_key,
        'measurement_types': measurement_types
    }

def create_spss_variable_names(questions: Dict[str, Dict[str, Any]]) -> Dict[str, str]:
    """Create valid SPSS variable names from question keys."""
    spss_names = {}
    name_counter = {}
    
    for original_key in questions.keys():
        # If it's already a valid short name (like Schl_1, Alt_1), keep it
        if len(original_key) <= 64 and not '-' in original_key and original_key.replace('_', '').replace('OFF', '').replace('MERK', '').replace('CUSTOM', '').replace('PAGE', '').isalnum():
            spss_names[original_key] = original_key
        else:
            # Create a new variable name for UUID-like keys
            if original_key.count('-') == 4 and len(original_key) == 36:  # UUID format
                # Generate a short name like Q001, Q002, etc.
                counter = len([k for k in spss_names.values() if k.startswith('Q')])
                new_name = f"Q{counter+1:03d}"
                spss_names[original_key] = new_name
            else:
                # For other long names, try to shorten them
                clean_name = original_key.replace('-', '_').replace(' ', '_')[:64]
                if clean_name in spss_names.values():
                    # Add counter if name already exists
                    base_name = clean_name[:60]  # Leave room for counter
                    counter = name_counter.get(base_name, 1)
                    while f"{base_name}_{counter}" in spss_names.values():
                        counter += 1
                    name_counter[base_name] = counter + 1
                    spss_names[original_key] = f"{base_name}_{counter}"
                else:
                    spss_names[original_key] = clean_name
    
    return spss_names

def process_responses(responses_data: List[Dict[str, Any]], mappings: Dict[str, Dict[str, Any]]) -> Tuple[pd.DataFrame, Dict[str, str]]:
    """Process responses using the mappings created from survey structure."""
    processed_responses = []
    
    # Create SPSS-compatible variable names
    spss_names = create_spss_variable_names(mappings['questions'])
    
    for response in responses_data:
        # Initialize response dict
        processed = {
            'response_id': response['id'],
            'created_at': response.get('createdAt', None)
        }
        
        # Initialize all questions with appropriate default values
        for key in mappings['questions'].keys():
            spss_name = spss_names[key]
            if mappings['questions'][key]['type'] == 'Text':
                processed[spss_name] = ''  # Empty string for text fields
            else:
                processed[spss_name] = -999  # -999 for numeric fields
        
        # Process each answer
        for answer in response.get('answers', []):
            question_key = None
            value = None
            
            if answer['@type'] == 'matrix':
                row_id = str(answer['row_id'])
                question_key = mappings['id_to_key'].get(row_id)
                value = answer.get('value')
                
            elif answer['@type'] == 'choice':
                choice_id = str(answer.get('choice_id'))
                question_key = mappings['choice_to_key'].get(choice_id)
                value = answer.get('value')
                
            elif answer['@type'] == 'number':
                element_id = str(answer['element_id'])
                question_key = mappings['element_to_key'].get(element_id)
                value = answer.get('value')
                
            elif answer['@type'] == 'text':
                element_id = str(answer['element_id'])
                question_key = mappings['element_to_key'].get(element_id)
                # For text fields, store the actual text content
                text_content = answer.get('text', '')
                if text_content and text_content.strip():
                    value = text_content.strip()  # Store actual text
                else:
                    value = ''  # Empty string for no content
            
            # Update processed response if we have valid data
            if question_key is not None and value is not None:
                spss_var_name = spss_names.get(question_key, question_key)
                processed[spss_var_name] = value
        
        processed_responses.append(processed)
    
    return pd.DataFrame(processed_responses), spss_names

def main():
    print("=== WORKEY SURVEY DATA PROCESSOR ===")
    print()
    
    # Get inputs
    if len(sys.argv) > 2:
        survey_id = sys.argv[1]
        token = sys.argv[2]
    else:
        survey_id = input("Enter Survey ID (e.g. 10551): ").strip()
        token = input("Enter API Token: ").strip()
    
    try:
        # Download data
        survey_data, responses_data = download_survey_data(survey_id, token)
        
        # Process data
        print("\nProcessing survey data...")
        mappings = create_question_mapping(survey_data)
        df, spss_names = process_responses(responses_data, mappings)
        
        # Create column labels using SPSS-compatible variable names
        column_labels = {}
        for original_key, qdef in mappings['questions'].items():
            spss_var_name = spss_names[original_key]
            column_labels[spss_var_name] = qdef['text']
        
        # Add labels for metadata columns
        column_labels['response_id'] = 'Response ID'
        column_labels['created_at'] = 'Created At'
        
        # Create value labels using SPSS-compatible variable names
        spss_value_labels = {}
        for original_key, labels in mappings['value_labels'].items():
            spss_var_name = spss_names[original_key]
            spss_value_labels[spss_var_name] = labels
        
        # Convert columns to appropriate data types
        text_variables = set()
        for original_key, question_def in mappings['questions'].items():
            spss_name = spss_names[original_key]
            if question_def['type'] == 'Text':
                text_variables.add(spss_name)
        
        # Convert numeric columns, keep text columns as strings
        for col in df.columns:
            if col in text_variables:
                # Keep as string, fill NaN with empty string
                df[col] = df[col].fillna('').astype(str)
            elif col in ['response_id', 'created_at']:
                # Keep metadata as is
                continue
            else:
                # Convert other columns to numeric
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(-999).astype(int)
        
        # Create output directory
        output_dir = get_downloads_folder() / f'survey_{survey_id}'
        output_dir.mkdir(exist_ok=True)
        
        # Save CSV (always works)
        csv_path = output_dir / f'survey_{survey_id}_responses.csv'
        df.to_csv(csv_path, index=False)
        print(f"\n✓ CSV saved: {csv_path}")
        
        # Save Excel with metadata
        excel_path = output_dir / f'survey_{survey_id}_data.xlsx'
        with pd.ExcelWriter(excel_path, engine='openpyxl') as writer:
            # Write responses
            df.to_excel(writer, sheet_name='Responses', index=False)
            
            # Write variable labels with SPSS names
            labels_df = pd.DataFrame([
                {
                    'SPSS_Variable': spss_names[key], 
                    'Original_Key': key,
                    'Label': qdef['text'], 
                    'Type': qdef['type']
                }
                for key, qdef in mappings['questions'].items()
            ])
            labels_df.to_excel(writer, sheet_name='Variable_Labels', index=False)
            
            # Write value labels
            value_labels_data = []
            for original_key, labels in mappings['value_labels'].items():
                spss_var = spss_names[original_key]
                for value, label in labels.items():
                    value_labels_data.append({
                        'SPSS_Variable': spss_var,
                        'Original_Key': original_key,
                        'Value': value,
                        'Label': label
                    })
            if value_labels_data:
                value_labels_df = pd.DataFrame(value_labels_data)
                value_labels_df.to_excel(writer, sheet_name='Value_Labels', index=False)
        
        print(f"✓ Excel saved: {excel_path}")
        
        # Try to save SPSS if available
        if SPSS_AVAILABLE:
            try:
                # Create measurement info for SPSS using SPSS-compatible variable names
                measurement_info = {}
                for col in df.columns:
                    # Find original key for this SPSS variable name
                    original_key = None
                    for orig, spss_name in spss_names.items():
                        if spss_name == col:
                            original_key = orig
                            break
                    
                    if original_key and original_key in mappings['measurement_types']:
                        if mappings['questions'][original_key]['type'] == 'Text':
                            measurement_info[col] = 'nominal'  # Text variables are nominal
                        else:
                            measurement_info[col] = 'scale' if mappings['measurement_types'][original_key] == 'Scale' else 'nominal'
                    else:
                        measurement_info[col] = 'nominal'  # Default to nominal for non-mapped columns
                
                # Try to save SPSS file
                spss_path = output_dir / f'survey_{survey_id}.sav'
                pyreadstat.write_sav(
                    df,
                    str(spss_path),
                    column_labels=column_labels,
                    variable_value_labels=spss_value_labels,
                    variable_measure=measurement_info
                )
                print(f"✓ SPSS saved: {spss_path}")
                
            except Exception as e:
                print(f"Note: Could not save SPSS file with text fields. Trying fallback method...")
                
                # Fallback: convert text variables to numeric codes for SPSS compatibility
                df_numeric = df.copy()
                text_value_labels = {}
                
                for col in text_variables:
                    if col in df_numeric.columns:
                        # Create numeric codes for unique text values
                        unique_texts = df_numeric[col].unique()
                        text_to_code = {text: idx for idx, text in enumerate(unique_texts) if text != ''}
                        text_to_code[''] = -999  # Empty text = missing
                        
                        # Convert to numeric
                        df_numeric[col] = df_numeric[col].map(text_to_code).fillna(-999).astype(int)
                        
                        # Create value labels for the codes
                        code_to_text = {code: text for text, code in text_to_code.items() if text != ''}
                        if code_to_text:
                            text_value_labels[col] = code_to_text
                
                # Merge text value labels with existing value labels
                combined_value_labels = {**spss_value_labels, **text_value_labels}
                
                try:
                    pyreadstat.write_sav(
                        df_numeric,
                        str(spss_path),
                        column_labels=column_labels,
                        variable_value_labels=combined_value_labels,
                        variable_measure=measurement_info
                    )
                    print(f"✓ SPSS saved with text variables converted to numeric codes")
                    
                    # Save text mapping info
                    if text_value_labels:
                        text_mapping_path = output_dir / 'text_variable_codes.txt'
                        with open(text_mapping_path, 'w', encoding='utf-8') as f:
                            f.write("Text Variable Numeric Codes\n")
                            f.write("===========================\n\n")
                            for col, codes in text_value_labels.items():
                                f.write(f"{col}:\n")
                                for code, text in sorted(codes.items()):
                                    f.write(f"  {code}: {text}\n")
                                f.write("\n")
                        print(f"✓ Text mapping saved: {text_mapping_path}")
                        
                except Exception as e2:
                    print(f"Note: SPSS export failed ({e2}). Use Excel file instead.")
        
        # Save metadata
        metadata = {
            'survey_id': survey_id,
            'total_responses': len(df),
            'total_questions': len(mappings['questions']),
            'questions': mappings['questions'],
            'measurement_types': mappings['measurement_types'],
            'value_labels': mappings['value_labels'],
            'spss_variable_mapping': spss_names,
            'text_variables': list(text_variables)
        }
        
        metadata_path = output_dir / f'survey_{survey_id}_metadata.json'
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        print(f"✓ Metadata saved: {metadata_path}")
        
        # Save raw data
        raw_survey_path = output_dir / 'survey.json'
        with open(raw_survey_path, 'w', encoding='utf-8') as f:
            json.dump(survey_data, f, ensure_ascii=False, indent=2)
        
        raw_replies_path = output_dir / 'replies.json'
        with open(raw_replies_path, 'w', encoding='utf-8') as f:
            json.dump(responses_data, f, ensure_ascii=False, indent=2)
        print(f"✓ Raw data saved")
        
        # Print summary info
        print(f"\n✓ SUCCESS! All files saved to: {output_dir}")
        print(f"\nSummary:")
        print(f"  - Total responses: {len(df)}")
        print(f"  - Total questions: {len(mappings['questions'])}")
        print(f"  - Text questions: {len(text_variables)}")
        print(f"  - Files created: CSV, Excel, Metadata, Raw JSON" + (" SPSS" if SPSS_AVAILABLE else ""))
        
        # Show variable name mapping for reference
        print(f"\nVariable name mapping (first 10):")
        for i, (orig, spss) in enumerate(spss_names.items()):
            if i >= 10:
                print(f"  ... and {len(spss_names) - 10} more")
                break
            var_type = mappings['questions'][orig]['type']
            print(f"  {spss} <- {orig} ({var_type})")
        
    except requests.exceptions.HTTPError as e:
        print(f"\n✗ API Error: {e}")
        print("Please check your Survey ID and API Token.")
    except Exception as e:
        print(f"\n✗ Error: {e}")
        print("Please contact support with this error message.")
    
    # Keep window open
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()