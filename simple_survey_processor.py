#!/usr/bin/env python3

import json
import pandas as pd
import pyreadstat
from typing import Dict, Any, List, Tuple
import numpy as np
import requests
import os
import sys
from pathlib import Path

def get_downloads_folder():
    """Get the Downloads folder path for the current OS."""
    home = Path.home()
    return home / "Downloads"

def get_environment_url():
    """Get the base URL based on user's environment selection."""
    print("Select environment:")
    print("  1. Test  (https://backend-test.workey.ai)")
    print("  2. Stage (https://backend-stage.workey.ai)")
    print("  3. Prod  (https://backend.workey.ai)")
    print()
    
    while True:
        choice = input("Enter your choice (1, 2, or 3): ").strip()
        
        if choice == "1":
            return "https://backend-test.workey.ai"
        elif choice == "2":
            return "https://backend-stage.workey.ai"
        elif choice == "3":
            return "https://backend.workey.ai"
        else:
            print("Invalid choice. Please enter 1, 2, or 3.")

def download_survey_data(survey_id: str, token: str, base_url: str, output_dir: Path) -> tuple[Dict, List]:
    """Download survey structure and responses from API."""
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    
    # Create output directory if it doesn't exist
    survey_dir = output_dir / f"survey_{survey_id}"
    survey_dir.mkdir(exist_ok=True)
    
    # Download survey structure
    print(f"Downloading survey structure for survey {survey_id}...")
    survey_url = f"{base_url}/surveys/{survey_id}"
    try:
        survey_response = requests.get(survey_url, headers=headers)
        survey_response.raise_for_status()
        survey_data = survey_response.json()
        
        # Save survey data
        survey_path = survey_dir / "survey.json"
        with open(survey_path, 'w', encoding='utf-8') as f:
            json.dump(survey_data, f, ensure_ascii=False, indent=2)
        print(f"✓ Survey structure saved to: {survey_path}")
        
    except requests.exceptions.RequestException as e:
        print(f"✗ Error downloading survey structure: {e}")
        print(f"  URL attempted: {survey_url}")
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    # Download responses
    print(f"Downloading responses for survey {survey_id}...")
    replies_url = f"{base_url}/surveys/{survey_id}/replies/"
    try:
        replies_response = requests.get(replies_url, headers=headers)
        replies_response.raise_for_status()
        replies_data = replies_response.json()
        
        # Save replies data
        replies_path = survey_dir / "replies.json"
        with open(replies_path, 'w', encoding='utf-8') as f:
            json.dump(replies_data, f, ensure_ascii=False, indent=2)
        print(f"✓ Responses saved to: {replies_path}")
        
    except requests.exceptions.RequestException as e:
        print(f"✗ Error downloading responses: {e}")
        print(f"  URL attempted: {replies_url}")
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    return survey_data, replies_data, survey_dir

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
    print("=" * 60)
    print("WORKEY SURVEY DATA PROCESSOR")
    print("=" * 60)
    print("\nThis tool will download and process survey data from Workey.")
    print("You will need:")
    print("  1. Select your environment (test/stage/prod)")
    print("  2. Your Survey ID (e.g., 10551)")
    print("  3. Your API Token")
    print("\n" + "=" * 60 + "\n")
    
    # Get environment selection
    base_url = get_environment_url()
    env_name = "Test" if "test" in base_url else "Stage" if "stage" in base_url else "Prod"
    print(f"\n✓ Selected environment: {env_name} ({base_url})\n")
    
    # Get user input
    survey_id = input("Enter Survey ID: ").strip()
    if not survey_id:
        print("Error: Survey ID cannot be empty!")
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    token = input("Enter API Token: ").strip()
    if not token:
        print("Error: Token cannot be empty!")
        input("\nPress Enter to exit...")
        sys.exit(1)
    
    # Get Downloads folder
    downloads_dir = get_downloads_folder()
    
    print(f"\n🚀 Starting Survey Data Processing")
    print(f"=" * 50)
    print(f"Environment: {env_name}")
    print(f"Base URL: {base_url}")
    print(f"Survey ID: {survey_id}")
    print(f"Output directory: {downloads_dir}")
    print(f"=" * 50 + "\n")
    
    # Download data
    survey_data, responses_data, output_dir = download_survey_data(
        survey_id, 
        token,
        base_url,
        downloads_dir
    )
    
    print("\n📊 Processing survey data...")
    
    # Create mappings
    mappings = create_question_mapping(survey_data)
    
    # Process responses
    df, spss_names = process_responses(responses_data, mappings)
    
    # Create column labels for SPSS using SPSS-compatible variable names
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
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(-999).astype(int)
        else:
            # Convert other columns to numeric
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(-999).astype(int)
    
    # Print summary info
    print(f"\n📈 Data Summary:")
    print(f"  - Total responses: {len(df)}")
    print(f"  - Total questions: {len(mappings['questions'])}")
    print(f"  - Text questions: {len(text_variables)}")
    print(f"  - Data shape: {df.shape}")
    
    # Show variable name mapping (first 10)
    print(f"\nVariable name mapping (first 10):")
    for i, (orig, spss) in enumerate(spss_names.items()):
        if i >= 10:
            print(f"  ... and {len(spss_names) - 10} more")
            break
        var_type = mappings['questions'][orig]['type']
        print(f"  {spss} <- {orig} ({var_type})")
    
    # Export to CSV
    csv_path = output_dir / f"survey_{survey_id}_responses.csv"
    df.to_csv(csv_path, index=False)
    print(f"\n✓ CSV exported to: {csv_path}")
    
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
    
    # Try to export to SPSS
    spss_path = output_dir / f"survey_{survey_id}.sav"
    try:
        pyreadstat.write_sav(
            df,
            str(spss_path),  # pyreadstat needs string path
            column_labels=column_labels,
            variable_value_labels=spss_value_labels,
            variable_measure=measurement_info
        )
        print(f"✓ SPSS file exported to: {spss_path}")
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
            print(f"✓ SPSS file saved with text variables converted to numeric codes")
            
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
            print(f"Even fallback method failed: {e2}")
    
    # Save metadata
    metadata = {
        'survey_id': survey_id,
        'environment': env_name,
        'base_url': base_url,
        'total_responses': len(df),
        'total_questions': len(mappings['questions']),
        'questions': mappings['questions'],
        'measurement_types': mappings['measurement_types'],
        'value_labels': mappings['value_labels'],
        'spss_variable_mapping': spss_names,
        'text_variables': list(text_variables)
    }
    
    metadata_path = output_dir / f"survey_{survey_id}_metadata.json"
    with open(metadata_path, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
    print(f"✓ Metadata saved to: {metadata_path}")
    
    print(f"\n✨ Processing complete! All files saved to:")
    print(f"   {output_dir}")
    print(f"\nFiles created:")
    print(f"  - survey.json (raw survey structure)")
    print(f"  - replies.json (raw responses)")
    print(f"  - survey_{survey_id}_responses.csv (processed data)")
    print(f"  - survey_{survey_id}.sav (SPSS file)")
    print(f"  - survey_{survey_id}_metadata.json (variable info)")
    if text_variables:
        print(f"  - text_variable_codes.txt (if text fields were converted)")
    
    print("\n" + "=" * 60)
    input("\nPress Enter to exit...")

if __name__ == "__main__":
    main()